"""Notion repository for Notion-Todoist sync"""
import datetime
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from notion_client import Client as NotionClient

from notion_todoist_sync.config import Configuration


class NotionRepository:
    """Handles all Notion-related operations"""

    def __init__(self, config: Configuration):
        self.client = NotionClient(auth=config.notion_token)
        self.database_id = config.notion_database_id
        self.config = config

    def get_recently_modified_tasks(self, minutes: int = 5) -> List[Dict[str, Any]]:
        """Get tasks modified in the last N minutes"""
        now = datetime.now(timezone.utc)
        n_minutes_ago = now - timedelta(minutes=minutes)

        response = self.client.databases.query(
            database_id=self.database_id,
            filter={
                "and": [
                    {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {
                            "after": n_minutes_ago.isoformat()
                        }
                    }
                ]
            }
        )

        return response["results"]

    def get_page(self, page_id: str) -> Dict[str, Any]:
        """Get a specific Notion page"""
        return self.client.pages.retrieve(page_id)

    def query_child_tasks(self, parent_page_id: str, exclude_completed: bool = True) -> List[Dict[str, Any]]:
        """Query for child tasks of a given parent"""
        parent_field = self.config.parent_task_field.get("name")
        if not parent_field:
            return []

        filters = [
            {
                "property": parent_field,
                "relation": {
                    "contains": parent_page_id
                }
            }
        ]

        if exclude_completed and self.config.completion_field:
            field_name = self.config.completion_field["name"]
            done_value = self.config.completion_field["done_value"]
            filters.append({
                "property": field_name,
                "status": {
                    "does_not_equal": done_value
                }
            })

        response = self.client.databases.query(
            database_id=self.database_id,
            filter={"and": filters}
        )

        return response["results"]

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Notion page with given properties"""
        return self.client.pages.update(page_id=page_id, properties=properties)

    def create_page(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Notion page with given properties"""
        return self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties
        )

    def archive_page(self, page_id: str) -> Dict[str, Any]:
        """Archive (soft delete) a Notion page"""
        return self.client.pages.update(page_id=page_id, archived=True)

    @staticmethod
    def get_field_value(field_value: Dict[str, Any]) -> Optional[str]:
        """Extract plain text value from a Notion field"""
        if not field_value:
            return None

        field_type = field_value["type"]
        if field_type == "title" and field_value["title"]:
            return field_value["title"][0]["plain_text"]
        elif field_type == "rich_text" and field_value["rich_text"]:
            return field_value["rich_text"][0]["plain_text"]
        elif field_type == "select" and field_value["select"]:
            return field_value["select"]["name"]
        elif field_type == "relation" and field_value["relation"]:
            return field_value["relation"][0]["id"]
        return None

    @staticmethod
    def parse_rich_text(rich_text_value: Dict[str, Any]) -> str:
        """Extract text from a rich_text field"""
        if not rich_text_value or not rich_text_value.get("rich_text"):
            return ""
        return rich_text_value["rich_text"][0]["plain_text"]

    @staticmethod
    def parse_select(select_value: Dict[str, Any]) -> Optional[str]:
        """Extract select option name"""
        if not select_value or not select_value.get("select"):
            return None
        return select_value["select"]["name"]

    @staticmethod
    def parse_multi_select(multi_select_value: Dict[str, Any]) -> List[str]:
        """Extract all select option names from multi_select"""
        if not multi_select_value or not multi_select_value.get("multi_select"):
            return []
        return [item["name"] for item in multi_select_value["multi_select"]]

    @staticmethod
    def parse_date(date_value: Dict[str, Any]) -> Optional[str]:
        """Extract date string from date field"""
        if not date_value or not date_value.get("date"):
            return None
        return date_value["date"]["start"]

    @staticmethod
    def parse_status(status_value: Dict[str, Any]) -> Optional[str]:
        """Extract status name from status field"""
        if not status_value or not status_value.get("status"):
            return None
        return status_value["status"]["name"]

    @staticmethod
    def build_title_property(text: str) -> Dict[str, Any]:
        """Build a title property value"""
        return {
            "title": [
                {
                    "text": {
                        "content": text
                    }
                }
            ]
        }

    @staticmethod
    def build_rich_text_property(text: str) -> Dict[str, Any]:
        """Build a rich_text property value"""
        return {
            "rich_text": [
                {
                    "text": {
                        "content": text
                    }
                }
            ]
        }

    @staticmethod
    def build_select_property(option_name: str) -> Dict[str, Any]:
        """Build a select property value"""
        return {
            "select": {
                "name": option_name
            }
        }

    @staticmethod
    def build_multi_select_property(option_names: List[str]) -> Dict[str, Any]:
        """Build a multi_select property value"""
        return {
            "multi_select": [{"name": name} for name in option_names]
        }

    @staticmethod
    def build_date_property(date_string: str) -> Dict[str, Any]:
        """Build a date property value"""
        return {
            "date": {
                "start": date_string
            }
        }

    @staticmethod
    def build_status_property(status_name: str) -> Dict[str, Any]:
        """Build a status property value"""
        return {
            "status": {
                "name": status_name
            }
        }
