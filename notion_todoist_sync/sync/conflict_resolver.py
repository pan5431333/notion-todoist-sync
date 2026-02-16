"""Conflict resolution strategies for bidirectional sync"""
from typing import Optional, Literal, Tuple
from datetime import datetime, timezone

from notion_todoist_sync.models import NotionTask, TodoistTask


ConflictResolutionStrategy = Literal["last_modified_wins", "notion_wins", "todoist_wins", "merge"]


class ConflictResolver:
    """Resolves conflicts between Notion and Todoist tasks"""

    def __init__(self, strategy: ConflictResolutionStrategy = "last_modified_wins"):
        self.strategy = strategy

    def resolve(
        self,
        notion_task: NotionTask,
        todoist_task: TodoistTask,
        sync_state: Optional[dict] = None
    ) -> Tuple[bool, str]:
        """
        Resolve a conflict between Notion and Todoist tasks.

        Returns:
            Tuple[bool, str]: (notion_wins, reason)
                - notion_wins: True if Notion data should win, False if Todoist wins
                - reason: Human-readable explanation of the decision
        """
        if self.strategy == "notion_wins":
            return True, "Configured to always prefer Notion"

        if self.strategy == "todoist_wins":
            return False, "Configured to always prefer Todoist"

        if self.strategy == "merge":
            return self._merge_strategy(notion_task, todoist_task)

        # Default: last_modified_wins
        return self._last_modified_wins(notion_task, todoist_task, sync_state)

    def _last_modified_wins(
        self,
        notion_task: NotionTask,
        todoist_task: TodoistTask,
        sync_state: Optional[dict] = None
    ) -> Tuple[bool, str]:
        """Use last modified timestamp to determine winner"""
        # If sync state exists, check if both sides changed since last sync
        if sync_state:
            last_sync = sync_state.get("last_synced_at")
            if last_sync:
                notion_changed = self._changed_since_last_sync(notion_task.last_edited_time, last_sync)
                todoist_changed = self._changed_since_last_sync(todoist_task.created_at, last_sync)

                if not notion_changed and todoist_changed:
                    return False, "Only Todoist changed since last sync"
                if notion_changed and not todoist_changed:
                    return True, "Only Notion changed since last sync"

        # Compare timestamps
        notion_time = notion_task.last_edited_time or notion_task.created_time
        todoist_time = todoist_task.created_at

        if not notion_time:
            return False, "Notion timestamp unavailable, Todoist wins"

        if not todoist_time:
            return True, "Todoist timestamp unavailable, Notion wins"

        if notion_time > todoist_time:
            return True, f"Notion modified more recently ({notion_time} > {todoist_time})"
        elif todoist_time > notion_time:
            return False, f"Todoist modified more recently ({todoist_time} > {notion_time})"
        else:
            # Timestamps are equal, prefer Notion as source of truth
            return True, "Timestamps equal, preferring Notion"

    def _merge_strategy(
        self,
        notion_task: NotionTask,
        todoist_task: TodoistTask
    ) -> Tuple[bool, str]:
        """
        Merge strategy - combine fields intelligently.
        Returns True to indicate Notion should be used as base for merge,
        False for Todoist as base.
        """
        # Prefer Notion's completion status (authoritative source)
        if notion_task.is_completed != todoist_task.is_completed:
            return True, "Preferring Notion completion status"

        # Prefer more recent due date
        if notion_task.due_date and todoist_task.due_date:
            if notion_task.due_date != todoist_task.due_date:
                # Notion date wins (assuming it's the planning tool)
                return True, "Preferring Notion due date"

        # Prefer higher priority
        if notion_task.priority and todoist_task.priority:
            if notion_task.priority != todoist_task.priority:
                # Higher number = lower priority in Todoist
                # We prefer the higher priority (lower number)
                if notion_task.priority < todoist_task.priority:
                    return True, f"Notion has higher priority ({notion_task.priority} < {todoist_task.priority})"
                else:
                    return False, f"Todoist has higher priority ({todoist_task.priority} < {notion_task.priority})"

        # If we get here, prefer Notion as base
        return True, "Using Notion as base for merge"

    @staticmethod
    def _changed_since_last_sync(
        last_modified: Optional[datetime],
        last_sync: str
    ) -> bool:
        """Check if a task changed since last sync"""
        if not last_modified:
            return False

        try:
            sync_time = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            # Ensure both datetimes are timezone-aware for comparison
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            if sync_time.tzinfo is None:
                sync_time = sync_time.replace(tzinfo=timezone.utc)
            return last_modified > sync_time
        except ValueError:
            return False

    @staticmethod
    def merge_tasks(
        notion_task: NotionTask,
        todoist_task: TodoistTask,
        base_notion: bool = True
    ) -> Tuple[NotionTask, TodoistTask]:
        """
        Merge two tasks, combining fields intelligently.

        Args:
            notion_task: The Notion task
            todoist_task: The Todoist task
            base_notion: True to use Notion as base, False to use Todoist as base

        Returns:
            Tuple[NotionTask, TodoistTask]: Merged tasks
        """
        # For Notion (base)
        if base_notion:
            # Use Todoist's due date if more recent
            if todoist_task.due_date and not notion_task.due_date:
                notion_task.due_date = todoist_task.due_date

            # Use Todoist's priority if higher (lower number)
            if todoist_task.priority and todoist_task.priority < (notion_task.priority or 999):
                notion_task.priority = todoist_task.priority

        # For Todoist (base)
        else:
            # Use Notion's completion status (authoritative)
            todoist_task.is_completed = notion_task.is_completed

            # Use Notion's title if available
            if notion_task.title and not todoist_task.content:
                todoist_task.content = notion_task.title

        return notion_task, todoist_task
