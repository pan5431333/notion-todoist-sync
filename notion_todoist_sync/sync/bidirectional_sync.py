"""Bidirectional sync engine for Notion-Todoist sync"""
import traceback
from typing import Optional, Dict, Any
from datetime import datetime, date

from notion_todoist_sync.config import Configuration
from notion_todoist_sync.models import NotionTask, TodoistTask
from notion_todoist_sync.repositories import NotionRepository, TodoistRepository
from notion_todoist_sync.mappers import BidirectionalFieldMapper
from notion_todoist_sync.sync.state import SyncStateRepository
from notion_todoist_sync.sync.conflict_resolver import ConflictResolver, ConflictResolutionStrategy


class BidirectionalSyncEngine:
    """Engine for bidirectional sync between Notion and Todoist"""

    def __init__(
        self,
        config: Configuration,
        notion_repo: NotionRepository,
        todoist_repo: TodoistRepository,
        sync_state_repo: SyncStateRepository,
        mapper: BidirectionalFieldMapper,
        conflict_strategy: ConflictResolutionStrategy = "last_modified_wins"
    ):
        self.config = config
        self.notion_repo = notion_repo
        self.todoist_repo = todoist_repo
        self.sync_state_repo = sync_state_repo
        self.mapper = mapper
        self.conflict_resolver = ConflictResolver(conflict_strategy)

    async def sync_task_from_notion(self, notion_page_id: str) -> Optional[str]:
        """
        Sync a task from Notion to Todoist.

        Returns the Todoist task ID on success, None on failure.
        """
        try:
            # Get Notion task
            notion_page = self.notion_repo.get_page(notion_page_id)
            notion_task = NotionTask.from_dict(notion_page, self.config.field_mapping)

            # Get existing sync state
            sync_state = self.sync_state_repo.get_by_notion_id(notion_page_id)

            # Find existing Todoist task
            todoist_task = None
            if sync_state:
                todoist_task_data = await self.todoist_repo.get_task(sync_state["todoist_id"])
                if todoist_task_data:
                    todoist_task = TodoistTask.from_dict(todoist_task_data)

            # Check for conflicts
            if todoist_task and self._has_conflict(notion_task, todoist_task, sync_state):
                notion_wins, reason = self.conflict_resolver.resolve(
                    notion_task, todoist_task, sync_state
                )
                print(f"Conflict detected: {reason}")

                if not notion_wins:
                    print("Todoist wins conflict, skipping sync")
                    self.sync_state_repo.update_timestamps(
                        notion_page_id,
                        notion_last_edited=str(notion_task.last_edited_time) if notion_task.last_edited_time else None
                    )
                    return None

            # Map Notion to Todoist
            todoist_fields = self.mapper.map_notion_to_todoist(notion_page)

            # Handle project mapping
            project_id = self._get_project_id_from_fields(todoist_fields)
            if project_id:
                todoist_fields["project_id"] = project_id
                todoist_fields.pop("project", None)

            # Handle due dates - Todoist SDK expects due_date as a date object
            if "due_date" in todoist_fields and "due_string" not in todoist_fields:
                due_value = todoist_fields.pop("due_date")
                if isinstance(due_value, str):
                    if "T" in due_value:
                        due_value = due_value.split("T")[0]
                    todoist_fields["due_date"] = datetime.strptime(due_value, "%Y-%m-%d").date()
                elif isinstance(due_value, date):
                    todoist_fields["due_date"] = due_value

            # Add From Notion label
            if "labels" not in todoist_fields:
                todoist_fields["labels"] = []
            if self.todoist_repo.from_notion_label and self.todoist_repo.from_notion_label not in todoist_fields["labels"]:
                todoist_fields["labels"].append(self.todoist_repo.from_notion_label)

            if not todoist_task:
                # Create new task - content is required
                if "content" not in todoist_fields or not todoist_fields["content"]:
                    print(f"Skipping Notion task {notion_page_id}: no content/title mapped")
                    return None
                task = await self.todoist_repo.create_task(**todoist_fields)
                await self.todoist_repo.add_comment(task.id, f"Notion ID: {notion_page_id}")
                print(f"Created new task {task.id} from Notion {notion_page_id}")
            else:
                # Update existing task
                if self.mapper.is_task_completed(notion_page):
                    if not todoist_task.is_completed:
                        await self.todoist_repo.complete_task(todoist_task.id)
                        print(f"Completed task {todoist_task.id}")
                else:
                    if todoist_task.is_completed:
                        await self.todoist_repo.reopen_task(todoist_task.id)
                        print(f"Reopened task {todoist_task.id}")
                    else:
                        # Update task fields
                        update_fields = self._prepare_update_fields(todoist_task, todoist_fields)
                        if update_fields:
                            await self.todoist_repo.update_task(todoist_task.id, **update_fields)
                            print(f"Updated task {todoist_task.id}")

            # Update sync state
            result_todoist_id = todoist_task.id if todoist_task else task.id
            self.sync_state_repo.upsert(
                notion_page_id,
                result_todoist_id,
                notion_last_edited=str(notion_task.last_edited_time) if notion_task.last_edited_time else None,
                sync_direction="notion_to_todoist"
            )

            return result_todoist_id

        except Exception as e:
            print(f"Error syncing Notion task {notion_page_id}: {e}")
            traceback.print_exc()
            return None

    async def sync_task_from_todoist(self, todoist_task_id: str) -> Optional[str]:
        """
        Sync a task from Todoist to Notion.

        Returns the Notion page ID on success, None on failure.
        """
        try:
            # Get Todoist task
            todoist_task_data = await self.todoist_repo.get_task(todoist_task_id)
            todoist_task = TodoistTask.from_dict(todoist_task_data)

            # Find Notion ID from comments
            notion_id = await self._get_notion_id_from_todoist_task(todoist_task_id)
            if not notion_id:
                print(f"No Notion ID found for Todoist task {todoist_task_id}")
                return None

            # Get existing Notion task
            notion_page = self.notion_repo.get_page(notion_id)
            notion_task = NotionTask.from_dict(notion_page, self.config.field_mapping)

            # Get existing sync state
            sync_state = self.sync_state_repo.get_by_notion_id(notion_id)

            # Check for conflicts
            if self._has_conflict(notion_task, todoist_task, sync_state):
                notion_wins, reason = self.conflict_resolver.resolve(
                    notion_task, todoist_task, sync_state
                )
                print(f"Conflict detected: {reason}")

                if notion_wins:
                    print("Notion wins conflict, skipping sync")
                    self.sync_state_repo.update_timestamps(
                        notion_id,
                        todoist_last_edited=str(todoist_task.created_at) if todoist_task.created_at else None
                    )
                    return None

            # Map Todoist to Notion
            notion_fields = self.mapper.map_todoist_to_notion(todoist_task)

            # Build Notion properties for update
            properties = self.mapper.build_notion_properties(todoist_task)

            # Update Notion task
            if properties:
                self.notion_repo.update_page(notion_id, properties)
                print(f"Updated Notion page {notion_id} from Todoist task {todoist_task_id}")

            # Handle completion status
            completion_field = self.config.completion_field
            if completion_field and todoist_task.is_completed != notion_task.is_completed:
                field_name = completion_field["name"]
                done_value = completion_field["done_value"]
                status_value = done_value if todoist_task.is_completed else "Not Started"

                status_property = {
                    field_name: {
                        "status": {
                            "name": status_value
                        }
                    }
                }
                self.notion_repo.update_page(notion_id, status_property)
                print(f"Updated completion status for Notion page {notion_id}")

            # Update sync state
            self.sync_state_repo.upsert(
                notion_id,
                todoist_task_id,
                todoist_last_edited=str(todoist_task.created_at) if todoist_task.created_at else None,
                sync_direction="todoist_to_notion"
            )

            return notion_id

        except Exception as e:
            print(f"Error syncing Todoist task {todoist_task_id}: {e}")
            traceback.print_exc()
            return None

    def _has_conflict(
        self,
        notion_task: NotionTask,
        todoist_task: TodoistTask,
        sync_state: Optional[dict]
    ) -> bool:
        """
        Check if there's a conflict between Notion and Todoist tasks.
        A conflict occurs when both sides have changed since last sync.
        """
        if not sync_state:
            return False

        last_sync = sync_state.get("last_synced_at")
        if not last_sync:
            return False

        # Check if Notion changed
        notion_changed = self._changed_since_last_sync(
            notion_task.last_edited_time or notion_task.created_time,
            last_sync
        )

        # Check if Todoist changed
        todoist_changed = self._changed_since_last_sync(
            todoist_task.created_at,
            last_sync
        )

        return notion_changed and todoist_changed

    @staticmethod
    def _changed_since_last_sync(last_modified: Optional[datetime], last_sync: str) -> bool:
        """Check if a task changed since last sync"""
        if not last_modified:
            return False

        try:
            sync_time = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            # Normalize timezone awareness for comparison
            if sync_time.tzinfo is not None and last_modified.tzinfo is None:
                sync_time = sync_time.replace(tzinfo=None)
            elif sync_time.tzinfo is None and last_modified.tzinfo is not None:
                last_modified = last_modified.replace(tzinfo=None)
            return last_modified > sync_time
        except (ValueError, TypeError):
            return False

    async def _get_notion_id_from_todoist_task(self, task_id: str) -> Optional[str]:
        """Get Notion ID from Todoist task comments"""
        try:
            comments_result = await self.todoist_repo.client.get_comments(task_id=task_id)

            # Handle pagination
            comments = []
            if hasattr(comments_result, '__aiter__'):
                async for page in comments_result:
                    if isinstance(page, list):
                        comments.extend(page)
                    else:
                        comments.append(page)
            elif hasattr(comments_result, '__iter__') and not isinstance(comments_result, (list, str)):
                for page in comments_result:
                    if isinstance(page, list):
                        comments.extend(page)
                    else:
                        comments.append(page)
            else:
                comments = comments_result if isinstance(comments_result, list) else [comments_result]

            for comment in comments:
                content = comment.content.strip()
                if "Notion ID:" in content:
                    notion_id = content.replace("Notion ID:", "").strip()
                    return notion_id

            return None
        except Exception as e:
            print(f"Error getting comments for task {task_id}: {e}")
            return None

    def _get_project_id_from_fields(self, todoist_fields: Dict[str, Any]) -> Optional[str]:
        """Get project ID from mapped fields"""
        if "project" in todoist_fields:
            project_name = todoist_fields["project"]
            project_id = self.todoist_repo.get_project_id(project_name)
            if project_id:
                print(f"Mapped project '{project_name}' to ID: {project_id}")
                return project_id
            else:
                print(f"Warning: Project '{project_name}' not found in Todoist")
        return None

    @staticmethod
    def _looks_like_recurrence(value: str) -> bool:
        """Check if a string looks like a recurrence pattern rather than a specific date"""
        if not value:
            return False
        lower = value.lower()
        recurrence_keywords = [
            "every", "daily", "weekly", "monthly", "yearly",
            "each", "workday", "weekday",
        ]
        return any(kw in lower for kw in recurrence_keywords)

    def _prepare_update_fields(self, task: TodoistTask, todoist_fields: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare fields for updating a Todoist task"""
        update_fields = {}

        # Defense-in-depth: skip due fields for recurring tasks unless the
        # incoming value is itself a recurrence pattern (e.g. "every day").
        # This prevents echoed date-only values from overwriting Todoist's
        # managed recurrence.
        skip_due = False
        if task.is_recurring:
            due_string_value = todoist_fields.get("due_string")
            if due_string_value and self._looks_like_recurrence(str(due_string_value)):
                skip_due = False  # Genuine recurrence update
            else:
                skip_due = True
                print(f"Skipping due fields for recurring task {task.id} (not a recurrence pattern)")

        # Handle due dates - Todoist SDK expects due_date as a date object
        if not skip_due and "due_string" in todoist_fields:
            update_fields["due_string"] = todoist_fields["due_string"]
        elif not skip_due and "due_date" in todoist_fields:
            due_val = todoist_fields["due_date"]
            if isinstance(due_val, str):
                if "T" in due_val:
                    due_val = due_val.split("T")[0]
                update_fields["due_date"] = datetime.strptime(due_val, "%Y-%m-%d").date()
            elif isinstance(due_val, date):
                update_fields["due_date"] = due_val

        # Handle other fields
        for field in ["content", "description", "priority"]:
            if field in todoist_fields:
                update_fields[field] = todoist_fields[field]

        # Handle project update
        if "project_id" in todoist_fields and todoist_fields["project_id"] != task.project_id:
            update_fields["project_id"] = todoist_fields["project_id"]
            print(f"Updating task {task.id} project to: {todoist_fields['project_id']}")

        # Handle labels - ensure From Notion label is present
        current_labels = task.labels or []
        if "labels" in todoist_fields:
            labels = todoist_fields["labels"]
        else:
            labels = current_labels.copy()

        if self.todoist_repo.from_notion_label and self.todoist_repo.from_notion_label not in labels:
            labels.append(self.todoist_repo.from_notion_label)
        update_fields["labels"] = labels

        return update_fields
