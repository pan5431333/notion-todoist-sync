"""Sync orchestrator for coordinating webhook events and sync"""
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from notion_todoist_sync.config import Configuration
from notion_todoist_sync.repositories import NotionRepository, TodoistRepository
from notion_todoist_sync.mappers import BidirectionalFieldMapper
from notion_todoist_sync.webhooks.todoist_webhook_receiver import app as todoist_webhook_app
from notion_todoist_sync.webhooks.notion_webhook_receiver import app as notion_webhook_app
from notion_todoist_sync.webhooks.webhook_manager import WebhookManager
from notion_todoist_sync.sync.state import SyncStateRepository
from notion_todoist_sync.sync.bidirectional_sync import BidirectionalSyncEngine
from notion_todoist_sync.sync.conflict_resolver import ConflictResolutionStrategy


class SyncOrchestrator:
    """Main orchestrator for coordinating sync between Notion and Todoist"""

    def __init__(
        self,
        config: Optional[Configuration] = None,
        conflict_strategy: ConflictResolutionStrategy = "last_modified_wins",
        poll_interval: int = 30  # seconds
    ):
        self.config = config or Configuration()
        self.poll_interval = poll_interval

        # Initialize repositories
        self.notion_repo = NotionRepository(self.config)
        self.todoist_repo = TodoistRepository(self.config)

        # Initialize sync state repository
        self.sync_state_repo = SyncStateRepository(self.config)

        # Initialize mapper
        self.mapper = BidirectionalFieldMapper(self.config, self.notion_repo)

        # Initialize sync engine
        self.sync_engine = BidirectionalSyncEngine(
            self.config,
            self.notion_repo,
            self.todoist_repo,
            self.sync_state_repo,
            self.mapper,
            conflict_strategy,
        )

        # Initialize webhook manager
        self.webhook_manager = WebhookManager(self.config, self.todoist_repo)

        # Event queue
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # Background task references
        self._event_processor_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._is_running = False

        # Statistics
        self._stats = {
            "todoist_events_processed": 0,
            "notion_events_processed": 0,
            "last_todoist_event_time": None,
            "last_notion_event_time": None,
            "active_sync_count": 0,
            "last_poll_time": None,
            "total_polls": 0,
        }

    async def initialize(self):
        """Initialize the orchestrator"""
        await self.todoist_repo.initialize()
        print("Sync orchestrator initialized")

    async def start(self):
        """Start the orchestrator and register webhooks"""
        if self._is_running:
            print("Orchestrator already running")
            return

        await self.initialize()

        # Set sync engine in webhook receivers
        from notion_todoist_sync.webhooks import todoist_webhook_receiver as tr
        from notion_todoist_sync.webhooks import notion_webhook_receiver as nr
        tr.set_sync_engine(self.sync_engine)
        tr.set_event_callback(self.queue_sync_event)
        nr.set_sync_engine(self.sync_engine)
        nr.set_event_callback(self.queue_sync_event)

        # Register webhooks
        if self.config.webhook_enabled:
            await self.webhook_manager.register_all_webhooks()
            print("Webhooks registered")

        # Start event processor
        self._is_running = True
        self._event_processor_task = asyncio.create_task(self._process_event_queue())
        print("Orchestrator started")

    async def stop(self):
        """Stop the orchestrator and clean up"""
        if not self._is_running:
            return

        self._is_running = False

        # Cancel event processor
        if self._event_processor_task:
            self._event_processor_task.cancel()
            try:
                await self._event_processor_task
            except asyncio.CancelledError:
                pass

        # Unregister webhooks
        if self.config.webhook_enabled:
            await self.webhook_manager.unregister_all_webhooks()
            print("Webhooks unregistered")

        print("Orchestrator stopped")

    def queue_sync_event(self, source: str, event_type: str, data: Dict[str, Any]):
        """Queue a sync event for processing"""
        event = {
            "source": source,
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._event_queue.put_nowait(event)

    async def _process_event_queue(self):
        """Process sync events from the queue"""
        while self._is_running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)

                source = event["source"]
                event_type = event["event_type"]
                data = event["data"]

                if source == "todoist":
                    await self._process_todoist_event(event_type, data)
                elif source == "notion":
                    await self._process_notion_event(event_type, data)

                self._event_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Error processing event: {e}")

    async def _process_todoist_event(self, event_type: str, data: Dict[str, Any]):
        """Process a Todoist event"""
        self._stats["todoist_events_processed"] += 1
        self._stats["last_todoist_event_time"] = datetime.utcnow().isoformat()

        task_id = data.get("task_id")
        if not task_id:
            return

        try:
            self._stats["active_sync_count"] += 1

            if event_type == "item:deleted":
                # Handle deletion
                notion_id = await self.sync_engine._get_notion_id_from_todoist_task(task_id)
                if notion_id:
                    if self.config.sync_deletions:
                        self.notion_repo.archive_page(notion_id)
                        print(f"Archived Notion page {notion_id} due to Todoist deletion")
                    else:
                        print(f"Skipping deletion sync (sync_deletions=false)")
            else:
                # Sync the task
                await self.sync_engine.sync_task_from_todoist(task_id)

        except Exception as e:
            print(f"Error processing Todoist event {event_type}: {e}")
        finally:
            self._stats["active_sync_count"] -= 1

    async def _process_notion_event(self, event_type: str, data: Dict[str, Any]):
        """Process a Notion event"""
        self._stats["notion_events_processed"] += 1
        self._stats["last_notion_event_time"] = datetime.utcnow().isoformat()

        page_id = data.get("page_id")
        if not page_id:
            return

        try:
            self._stats["active_sync_count"] += 1

            if event_type == "page.deleted":
                # Handle deletion
                sync_state = self.sync_state_repo.get_by_notion_id(page_id)
                if sync_state and self.config.sync_deletions:
                    todoist_id = sync_state.get("todoist_id")
                    if todoist_id:
                        await self.todoist_repo.delete_task(todoist_id)
                        self.sync_state_repo.delete(page_id)
                        print(f"Deleted Todoist task {todoist_id} due to Notion deletion")
                else:
                    print(f"Skipping deletion sync (sync_deletions=false)")
            else:
                # Sync the page
                await self.sync_engine.sync_task_from_notion(page_id)

        except Exception as e:
            print(f"Error processing Notion event {event_type}: {e}")
        finally:
            self._stats["active_sync_count"] -= 1

    async def run_full_sync(self):
        """Run a full sync from Notion to Todoist (backward compatibility)"""
        print("Running full sync from Notion to Todoist...")

        # Get recently modified Notion tasks
        notion_tasks = self.notion_repo.get_recently_modified_tasks(minutes=5)

        # Get all Todoist tasks
        todoist_tasks = await self.todoist_repo.get_tasks()

        # Build mapping
        task_notion_map = await self.todoist_repo.get_notion_ids_for_tasks(todoist_tasks)

        # Process each Notion task
        for notion_task in notion_tasks:
            await self.sync_engine.sync_task_from_notion(notion_task["id"])

        print(f"Full sync completed. Processed {len(notion_tasks)} tasks.")

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the orchestrator"""
        from notion_todoist_sync.webhooks import todoist_webhook_receiver, notion_webhook_receiver

        return {
            "is_running": self._is_running,
            "stats": self._stats.copy(),
            "webhooks": self.webhook_manager.get_webhook_status(),
            "last_todoist_webhook_event": todoist_webhook_receiver.get_last_webhook_event(),
            "last_notion_webhook_event": notion_webhook_receiver.get_last_webhook_event(),
            "sync_state_count": self.sync_state_repo.count(),
        }
