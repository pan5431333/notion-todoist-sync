"""Configuration management for Notion-Todoist sync"""
import os
import json
from typing import Dict, Any, Optional

from dotenv import load_dotenv


class Configuration:
    """Handles loading and managing sync configuration"""

    def __init__(self, config_path: Optional[str] = None, webhook_config_path: Optional[str] = None):
        load_dotenv()
        print("Loaded environment variables")

        # Load API tokens and IDs
        self.notion_token = os.getenv("NOTION_TOKEN")
        self.notion_database_id = os.getenv("NOTION_DATABASE_ID")
        self.todoist_token = os.getenv("TODOIST_TOKEN")

        print(f"Notion Token exists: {bool(self.notion_token)}")
        print(f"Notion Database ID exists: {bool(self.notion_database_id)}")
        print(f"Todoist Token exists: {bool(self.todoist_token)}")

        # Load sync configuration
        config_path = config_path or os.getenv(
            "SYNC_CONFIG_PATH", os.path.join("config", "sync_config.json")
        )
        self.config = self._load_config(config_path)

        # Load webhook configuration
        webhook_config_path = webhook_config_path or os.getenv(
            "WEBHOOK_CONFIG_PATH", os.path.join("config", "webhook_config.json")
        )
        self.webhook_config = self._load_webhook_config(webhook_config_path)

    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        with open(path, "r") as f:
            return json.load(f)

    def _load_webhook_config(self, path: str) -> Dict[str, Any]:
        """Load webhook configuration from JSON file"""
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default webhook config if file doesn't exist
            return {
                "webhooks": {
                    "enabled": False,
                    "todoist": {"enabled": False, "secret": None},
                    "notion": {"enabled": False, "secret": None},
                }
            }

    @property
    def field_mapping(self) -> Dict[str, str]:
        """Get field mapping from Notion to Todoist"""
        return self.config.get("field_mapping", {})

    @property
    def description_fields(self) -> Dict[str, Any]:
        """Get description field configuration"""
        return self.config.get("description_fields", {})

    @property
    def parent_task_field(self) -> Dict[str, Any]:
        """Get parent task field configuration"""
        return self.config.get("parent_task_field", {})

    @property
    def completion_field(self) -> Dict[str, Any]:
        """Get completion field configuration"""
        return self.config.get("completion_field", {})

    @property
    def bidirectional_sync(self) -> Dict[str, Any]:
        """Get bidirectional sync configuration"""
        return self.config.get("bidirectional_sync", {"enabled": False})

    @property
    def webhook_enabled(self) -> bool:
        """Check if webhooks are enabled"""
        return self.webhook_config.get("webhooks", {}).get("enabled", False)

    @property
    def todoist_webhook_config(self) -> Dict[str, Any]:
        """Get Todoist webhook configuration"""
        return self.webhook_config.get("webhooks", {}).get("todoist", {})

    @property
    def notion_webhook_config(self) -> Dict[str, Any]:
        """Get Notion webhook configuration"""
        return self.webhook_config.get("webhooks", {}).get("notion", {})

    @property
    def webhook_url(self) -> Optional[str]:
        """Get the public webhook URL"""
        return os.getenv("WEBHOOK_URL")

    @property
    def webhook_port(self) -> int:
        """Get the webhook server port"""
        return int(os.getenv("WEBHOOK_PORT", "8000"))

    @property
    def todoist_webhook_secret(self) -> Optional[str]:
        """Get Todoist webhook secret"""
        return self.todoist_webhook_config.get("secret") or os.getenv("TODOIST_WEBHOOK_SECRET")

    @property
    def notion_webhook_secret(self) -> Optional[str]:
        """Get Notion webhook secret"""
        return self.notion_webhook_config.get("secret") or os.getenv("NOTION_WEBHOOK_SECRET")

    @property
    def conflict_resolution_strategy(self) -> str:
        """Get conflict resolution strategy"""
        return os.getenv(
            "CONFLICT_RESOLUTION_STRATEGY",
            self.config.get("bidirectional_sync", {}).get("conflict_resolution", "last_modified_wins")
        )

    @property
    def sync_state_db_path(self) -> str:
        """Get path to sync state database"""
        return os.getenv("SYNC_STATE_DB_PATH", "sync_state.db")

    @property
    def sync_deletions(self) -> bool:
        """Check if deletions should be synced"""
        return self.config.get("bidirectional_sync", {}).get("sync_deletions", False)
