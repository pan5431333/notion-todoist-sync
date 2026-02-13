"""Domain models for Notion and Todoist tasks"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class NotionTask:
    """Represents a task from Notion"""
    id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    project: Optional[str] = None
    labels: Optional[List[str]] = field(default_factory=list)
    parent_id: Optional[str] = None
    is_completed: bool = False
    last_edited_time: Optional[datetime] = None
    created_time: Optional[datetime] = None
    properties: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], field_mapping: Dict[str, str]) -> "NotionTask":
        """Create NotionTask from raw Notion API response"""
        # Extract title
        title = ""
        title_prop = data["properties"].get(list(field_mapping.values())[0]) if field_mapping else None
        if not title_prop:
            # Find first title field
            for prop_name, prop_value in data["properties"].items():
                if prop_value.get("type") == "title" and prop_value.get("title"):
                    title = prop_value["title"][0]["plain_text"]
                    break
        elif title_prop and title_prop.get("title"):
            title = title_prop["title"][0]["plain_text"]

        # Extract timestamps
        last_edited_time = None
        if data.get("last_edited_time"):
            last_edited_time = datetime.fromisoformat(data["last_edited_time"].replace("Z", "+00:00"))

        created_time = None
        if data.get("created_time"):
            created_time = datetime.fromisoformat(data["created_time"].replace("Z", "+00:00"))

        # Extract completion status from properties
        is_completed = False
        completion_field = field_mapping.get("completion_field")
        if completion_field and completion_field in data["properties"]:
            status_prop = data["properties"][completion_field]
            if status_prop.get("type") == "status" and status_prop.get("status"):
                is_completed = status_prop["status"]["name"] == "Done"

        return cls(
            id=data["id"],
            title=title,
            properties=data["properties"],
            last_edited_time=last_edited_time,
            created_time=created_time,
            is_completed=is_completed,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API calls"""
        return {
            "id": self.id,
            "title": self.title,
            "properties": self.properties,
            "is_completed": self.is_completed,
        }


@dataclass
class TodoistTask:
    """Represents a task from Todoist"""
    id: str
    content: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: int = 1
    project_id: Optional[str] = None
    labels: Optional[List[str]] = field(default_factory=list)
    parent_id: Optional[str] = None
    is_completed: bool = False
    created_at: Optional[datetime] = None
    due_string: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any) -> "TodoistTask":
        """Create TodoistTask from raw Todoist API response"""
        # Extract due information
        due_date = None
        due_string = None
        if hasattr(data, 'due') and data.due:
            if hasattr(data.due, 'date'):
                due_date = data.due.date
            if hasattr(data.due, 'string'):
                due_string = data.due.string

        # Extract created timestamp
        created_at = None
        if hasattr(data, 'created_at') and data.created_at:
            if isinstance(data.created_at, datetime):
                created_at = data.created_at
            elif isinstance(data.created_at, str):
                created_at = datetime.fromisoformat(data.created_at.replace("Z", "+00:00"))

        # Extract labels
        labels = []
        if hasattr(data, 'labels') and data.labels:
            labels = data.labels

        # Extract priority
        priority = 1
        if hasattr(data, 'priority'):
            priority = data.priority

        # Extract completion status
        is_completed = False
        if hasattr(data, 'is_completed'):
            is_completed = data.is_completed

        # Extract parent ID
        parent_id = None
        if hasattr(data, 'parent_id'):
            parent_id = str(data.parent_id) if data.parent_id else None

        # Extract project ID
        project_id = None
        if hasattr(data, 'project_id'):
            project_id = str(data.project_id) if data.project_id else None

        # Extract description
        description = None
        if hasattr(data, 'description'):
            description = data.description

        return cls(
            id=str(data.id),
            content=data.content,
            description=description,
            due_date=due_date,
            due_string=due_string,
            priority=priority,
            project_id=project_id,
            labels=labels,
            parent_id=parent_id,
            is_completed=is_completed,
            created_at=created_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API calls"""
        result = {
            "content": self.content,
        }
        if self.description:
            result["description"] = self.description
        if self.due_date:
            result["due_date"] = self.due_date
        if self.due_string:
            result["due_string"] = self.due_string
        if self.priority != 1:
            result["priority"] = self.priority
        if self.project_id:
            result["project_id"] = self.project_id
        if self.labels:
            result["labels"] = self.labels
        if self.parent_id:
            result["parent_id"] = self.parent_id
        return result
