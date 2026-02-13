"""Sync state repository using SQLite for tracking sync state"""
import sqlite3
import os
from typing import Optional, Dict, List
from datetime import datetime
from contextlib import contextmanager

from notion_todoist_sync.config import Configuration


@contextmanager
def get_db_connection(db_path: str):
    """Context manager for database connections"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class SyncStateRepository:
    """Repository for tracking sync state between Notion and Todoist"""

    def __init__(self, config: Configuration):
        self.db_path = config.sync_state_db_path
        self._ensure_schema()

    def _ensure_schema(self):
        """Ensure the database schema exists"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_states (
                    notion_id TEXT PRIMARY KEY,
                    todoist_id TEXT NOT NULL,
                    notion_last_edited TEXT,
                    todoist_last_edited TEXT,
                    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_sync_direction TEXT,
                    conflict_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_todoist_id
                ON sync_states(todoist_id)
            """)

    def get_by_notion_id(self, notion_id: str) -> Optional[Dict]:
        """Get sync state by Notion ID"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sync_states WHERE notion_id = ?",
                (notion_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_by_todoist_id(self, todoist_id: str) -> Optional[Dict]:
        """Get sync state by Todoist ID"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sync_states WHERE todoist_id = ?",
                (todoist_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def upsert(
        self,
        notion_id: str,
        todoist_id: str,
        notion_last_edited: Optional[str] = None,
        todoist_last_edited: Optional[str] = None,
        sync_direction: str = "notion_to_todoist"
    ):
        """Insert or update sync state"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_states (
                    notion_id, todoist_id, notion_last_edited,
                    todoist_last_edited, last_synced_at, last_sync_direction
                ) VALUES (?, ?, ?, ?, datetime('now'), ?)
                ON CONFLICT(notion_id) DO UPDATE SET
                    todoist_id = excluded.todoist_id,
                    notion_last_edited = excluded.notion_last_edited,
                    todoist_last_edited = excluded.todoist_last_edited,
                    last_synced_at = datetime('now'),
                    last_sync_direction = excluded.last_sync_direction
            """, (notion_id, todoist_id, notion_last_edited, todoist_last_edited, sync_direction))

    def update_timestamps(
        self,
        notion_id: str,
        notion_last_edited: Optional[str] = None,
        todoist_last_edited: Optional[str] = None
    ):
        """Update timestamps for a sync state"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            if notion_last_edited:
                cursor.execute("""
                    UPDATE sync_states
                    SET notion_last_edited = ?, last_synced_at = datetime('now')
                    WHERE notion_id = ?
                """, (notion_last_edited, notion_id))
            if todoist_last_edited:
                cursor.execute("""
                    UPDATE sync_states
                    SET todoist_last_edited = ?, last_synced_at = datetime('now')
                    WHERE notion_id = ?
                """, (todoist_last_edited, notion_id))

    def increment_conflict_count(self, notion_id: str):
        """Increment conflict counter for a sync state"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_states
                SET conflict_count = conflict_count + 1
                WHERE notion_id = ?
            """, (notion_id,))

    def delete(self, notion_id: str):
        """Delete a sync state"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sync_states WHERE notion_id = ?",
                (notion_id,)
            )

    def get_all(self) -> List[Dict]:
        """Get all sync states"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sync_states ORDER BY last_synced_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Get count of sync states"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM sync_states")
            row = cursor.fetchone()
            return row["count"] if row else 0

    def get_stale_states(self, hours: int = 24) -> List[Dict]:
        """Get states that haven't been synced in the given hours"""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sync_states
                WHERE datetime(last_synced_at) < datetime('now', '-' || ? || ' hours')
                ORDER BY last_synced_at ASC
            """, (hours,))
            return [dict(row) for row in cursor.fetchall()]

    def migrate_from_notion_id_comments(self, task_notion_map: Dict[str, str]) -> int:
        """
        Migrate existing mappings from task_notion_map to sync_states table.
        Returns the number of migrated states.
        """
        migrated = 0
        for todoist_id, notion_id in task_notion_map.items():
            if not self.get_by_notion_id(notion_id):
                self.upsert(notion_id, todoist_id, sync_direction="migrated")
                migrated += 1
        return migrated
