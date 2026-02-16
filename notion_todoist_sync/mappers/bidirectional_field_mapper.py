"""Bidirectional field mapper for Notion-Todoist sync"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from notion_todoist_sync.config import Configuration
from notion_todoist_sync.models import NotionTask, TodoistTask
from notion_todoist_sync.repositories import NotionRepository


class BidirectionalFieldMapper:
    """Handles bidirectional mapping between Notion and Todoist task fields"""

    def __init__(self, config: Configuration, notion_repo: NotionRepository):
        self.config = config
        self.notion_repo = notion_repo

        # Reverse field mapping for Todoist -> Notion
        self._reverse_field_mapping = self._build_reverse_mapping()

    def _build_reverse_mapping(self) -> Dict[str, str]:
        """Build reverse mapping from Todoist fields to Notion fields"""
        reverse = {}
        for notion_field, todoist_field in self.config.field_mapping.items():
            reverse[todoist_field] = notion_field
        return reverse

    def map_notion_to_todoist(self, notion_task: Dict[str, Any]) -> Dict[str, Any]:
        """Map Notion task fields to Todoist fields"""
        todoist_fields = {}

        # Process regular field mappings
        for notion_field, todoist_field in self.config.field_mapping.items():
            if notion_field in notion_task["properties"]:
                value = notion_task["properties"][notion_field]
                print(f"Mapping field {notion_field} ({value['type']}) to {todoist_field}")

                mapped_value = self._map_notion_field_value(value, todoist_field)
                if mapped_value is not None:
                    todoist_fields[todoist_field] = mapped_value

        # Process description fields if enabled
        description = self._build_description(notion_task)
        if description:
            todoist_fields["description"] = description

        print(f"Final mapped fields: {todoist_fields}")
        return todoist_fields

    def map_todoist_to_notion(self, todoist_task: TodoistTask) -> Dict[str, Any]:
        """Map Todoist task fields to Notion fields"""
        notion_fields = {}

        # Map content to title
        if todoist_task.content:
            notion_fields["title"] = todoist_task.content

        # Map other fields using reverse mapping
        for todoist_field, notion_field in self._reverse_field_mapping.items():
            if notion_field == "title":
                continue  # Already handled above

            mapped_value = self._map_todoist_field_value(todoist_task, todoist_field, notion_field)
            if mapped_value is not None:
                notion_fields[notion_field] = mapped_value

        # Map description if it exists
        if todoist_task.description:
            notion_fields["description"] = todoist_task.description

        return notion_fields

    def _map_notion_field_value(self, value: Dict[str, Any], todoist_field: str) -> Any:
        """Map a single Notion field value to Todoist"""
        field_type = value["type"]

        if field_type == "title":
            if value["title"]:
                return value["title"][0]["plain_text"]

        elif field_type == "date":
            if value["date"]:
                return value["date"]["start"]

        elif field_type == "select":
            if value["select"]:
                if todoist_field == "priority":
                    return self._map_priority(value["select"]["name"])
                else:
                    return value["select"]["name"]

        elif field_type == "rich_text":
            if value["rich_text"]:
                return value["rich_text"][0]["plain_text"]

        elif field_type == "multi_select":
            if value["multi_select"]:
                return [item["name"] for item in value["multi_select"]]

        return None

    def _map_todoist_field_value(
        self,
        todoist_task: TodoistTask,
        todoist_field: str,
        notion_field: str
    ) -> Any:
        """Map a single Todoist field value to Notion"""
        if todoist_field == "content":
            return todoist_task.content

        elif todoist_field == "description":
            return todoist_task.description

        elif todoist_field == "due_date":
            return todoist_task.due_datetime or todoist_task.due_date

        elif todoist_field == "due_string":
            return todoist_task.due_string

        elif todoist_field == "priority":
            return self._reverse_map_priority(todoist_task.priority)

        elif todoist_field == "labels":
            return todoist_task.labels if todoist_task.labels else []

        return None

    def _map_priority(self, priority_value: str) -> int:
        """Map Notion priority to Todoist priority"""
        try:
            notion_priority = int(priority_value)
            # In Notion: 1 is highest, 3 is lowest
            # In Todoist: 4 is highest, 1 is lowest
            priority_map = {1: 4, 2: 3, 3: 2, 4: 1}
            todoist_priority = priority_map.get(notion_priority, 1)
            print(f"Priority mapping: Notion {priority_value} -> Todoist {todoist_priority}")
            return todoist_priority
        except (ValueError, TypeError):
            return 1  # Default priority

    def _reverse_map_priority(self, todoist_priority) -> str:
        """Map Todoist priority to Notion priority"""
        # In Notion: 1 is highest, 3 is lowest
        # In Todoist: 4 is highest, 1 is lowest
        priority_map = {4: 1, 3: 2, 2: 3, 1: 4}
        notion_priority = priority_map.get(int(todoist_priority), 4)
        return str(notion_priority)

    def _build_description(self, notion_task: Dict[str, Any]) -> Optional[str]:
        """Build description from configured fields"""
        description_config = self.config.description_fields
        if not description_config.get("enabled", False):
            return None

        description_parts = []

        for field_config in description_config.get("fields", []):
            field_name = field_config["name"]
            if field_name in notion_task["properties"]:
                value = notion_task["properties"][field_name]
                field_content = self._extract_field_content(value)

                if field_content:
                    formatted_content = field_config["format"].format(value=field_content)
                    description_parts.append(formatted_content)

        if description_parts:
            separator = description_config.get("separator", "\n\n")
            print(f"Added description from fields: {[f['name'] for f in description_config['fields']]}")
            return separator.join(description_parts)

        return None

    def _extract_field_content(self, value: Dict[str, Any]) -> Optional[str]:
        """Extract content from a field value for description"""
        field_type = value["type"]

        if field_type == "rich_text" and value["rich_text"]:
            return value["rich_text"][0]["plain_text"]
        elif field_type == "select" and value["select"]:
            return value["select"]["name"]
        elif field_type == "multi_select" and value["multi_select"]:
            return ", ".join(item["name"] for item in value["multi_select"])
        elif field_type == "date" and value["date"]:
            return value["date"]["start"]
        elif field_type == "checkbox":
            return "Yes" if value["checkbox"] else "No"
        elif field_type == "number":
            return str(value["number"]) if value["number"] is not None else ""

        return None

    def is_task_completed(self, notion_task: Dict[str, Any]) -> bool:
        """Check if a Notion task is completed"""
        completion_field = self.config.completion_field
        if not completion_field:
            return False

        field_name = completion_field["name"]
        done_value = completion_field["done_value"]

        if field_name in notion_task["properties"]:
            current_status = notion_task["properties"][field_name]
            if current_status["type"] == "status":
                return current_status["status"]["name"] == done_value

        return False

    def build_notion_properties(self, todoist_task: TodoistTask) -> Dict[str, Any]:
        """Build Notion property dict from Todoist task for API calls"""
        properties = {}

        # Map fields based on reverse mapping
        for todoist_field, notion_field in self._reverse_field_mapping.items():
            value = self._map_todoist_field_value(todoist_task, todoist_field, notion_field)
            if value is None:
                continue

            # Build property based on the todoist field type
            prop = self._build_notion_property(notion_field, todoist_field, value)
            if prop:
                properties.update(prop)

        return properties

    def _build_notion_property(self, notion_field: str, todoist_field: str, value: Any) -> Dict[str, Any]:
        """Build a Notion property value for API calls"""
        if todoist_field == "content":
            return {notion_field: self.notion_repo.build_title_property(value)}
        elif todoist_field == "due_date":
            return {notion_field: self.notion_repo.build_date_property(str(value))}
        elif todoist_field == "due_string":
            return {notion_field: self.notion_repo.build_rich_text_property(str(value))}
        elif todoist_field == "priority":
            return {notion_field: self.notion_repo.build_select_property(str(value))}
        elif todoist_field == "project":
            return {notion_field: self.notion_repo.build_select_property(str(value))}
        elif todoist_field == "labels":
            if isinstance(value, list):
                return {notion_field: self.notion_repo.build_multi_select_property(value)}
        return {}
