import os
import json
import asyncio
import datetime
from typing import Dict, List, Optional, Any, Tuple

def _patch_todoist_api():
    """Lazy patch Todoist API to work with new unified API v1"""
    try:
        import todoist_api_python.endpoints
        import todoist_api_python.http_requests
        import todoist_api_python.models
        from urllib.parse import urljoin
        
        # Patch endpoint to use /api/v1/ instead of /rest/v2/
        todoist_api_python.endpoints.REST_API = urljoin(
            todoist_api_python.endpoints.BASE_URL, "/api/v1/"
        )
        
        # Patch http_requests to handle the new API response format
        _original_get = todoist_api_python.http_requests.get
        _original_post = todoist_api_python.http_requests.post
        
        def _patch_get(*args, **kwargs):
            result = _original_get(*args, **kwargs)
            if isinstance(result, dict) and 'results' in result:
                return result['results']
            return result
        
        def _patch_post(*args, **kwargs):
            result = _original_post(*args, **kwargs)
            if isinstance(result, dict) and 'results' in result:
                if len(result) == 1:
                    return result['results']
                results = result['results']
                if len(results) == 1:
                    return results[0]
                return results
            return result
        
        todoist_api_python.http_requests.get = _patch_get
        todoist_api_python.http_requests.post = _patch_post
        
        # Patch Project.from_dict
        _original_project_from_dict = todoist_api_python.models.Project.from_dict
        
        def _patched_project_from_dict(cls, obj: dict):
            mapped_obj = obj.copy()
            if 'child_order' in mapped_obj and 'order' not in mapped_obj:
                mapped_obj['order'] = mapped_obj['child_order']
            if 'comment_count' not in mapped_obj:
                mapped_obj['comment_count'] = 0
            if 'url' not in mapped_obj:
                mapped_obj['url'] = f"https://todoist.com/app/project/{mapped_obj.get('id', '')}"
            if 'inbox_project' in mapped_obj and 'is_inbox_project' not in mapped_obj:
                mapped_obj['is_inbox_project'] = mapped_obj['inbox_project']
            if 'is_team_inbox' not in mapped_obj:
                mapped_obj['is_team_inbox'] = None
            return _original_project_from_dict(mapped_obj)
        
        todoist_api_python.models.Project.from_dict = classmethod(_patched_project_from_dict)
        
        # Patch Task.from_dict
        _original_task_from_dict = todoist_api_python.models.Task.from_dict
        
        def _patched_task_from_dict(cls, obj: dict):
            mapped_obj = obj.copy()
            if 'added_at' in mapped_obj and 'created_at' not in mapped_obj:
                mapped_obj['created_at'] = mapped_obj['added_at']
            if 'added_by_uid' in mapped_obj and 'creator_id' not in mapped_obj:
                mapped_obj['creator_id'] = mapped_obj['added_by_uid']
            if 'checked' in mapped_obj and 'is_completed' not in mapped_obj:
                mapped_obj['is_completed'] = mapped_obj['checked']
            if 'child_order' in mapped_obj and 'order' not in mapped_obj:
                mapped_obj['order'] = mapped_obj['child_order']
            if 'note_count' in mapped_obj and 'comment_count' not in mapped_obj:
                mapped_obj['comment_count'] = mapped_obj['note_count']
            elif 'comment_count' not in mapped_obj:
                mapped_obj['comment_count'] = 0
            if 'url' not in mapped_obj:
                task_id = mapped_obj.get('id', '')
                sync_id = mapped_obj.get('sync_id', '')
                if sync_id:
                    from todoist_api_python.utils import get_url_for_task
                    mapped_obj['url'] = get_url_for_task(task_id, sync_id)
                else:
                    mapped_obj['url'] = f"https://todoist.com/app/task/{task_id}"
            if 'project_id' not in mapped_obj:
                mapped_obj['project_id'] = mapped_obj.get('project_id') or ''
            return _original_task_from_dict(mapped_obj)
        
        todoist_api_python.models.Task.from_dict = classmethod(_patched_task_from_dict)
    except ImportError:
        # If imports fail, the patches will be applied when TodoistAPIAsync is first used
        pass

# Apply patches before importing TodoistAPIAsync
_patch_todoist_api()

from notion_client import Client as NotionClient
from todoist_api_python.api_async import TodoistAPIAsync
from dotenv import load_dotenv
from datetime import datetime, date, timezone, timedelta

print("Starting sync script...")


class Configuration:
    """Handles loading and managing sync configuration"""
    
    def __init__(self, config_path: Optional[str] = None):
        load_dotenv()
        print("Loaded environment variables")
        
        self.notion_token = os.getenv("NOTION_TOKEN")
        self.notion_database_id = os.getenv("NOTION_DATABASE_ID")
        self.todoist_token = os.getenv("TODOIST_TOKEN")
        
        print(f"Notion Token exists: {bool(self.notion_token)}")
        print(f"Notion Database ID exists: {bool(self.notion_database_id)}")
        print(f"Todoist Token exists: {bool(self.todoist_token)}")
        
        config_path = config_path or os.getenv("SYNC_CONFIG_PATH", os.path.join("config", "sync_config.json"))
        self.config = self._load_config(config_path)
    
    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        with open(path, "r") as f:
            return json.load(f)
    
    @property
    def field_mapping(self) -> Dict[str, str]:
        return self.config.get("field_mapping", {})
    
    @property
    def description_fields(self) -> Dict[str, Any]:
        return self.config.get("description_fields", {})
    
    @property
    def parent_task_field(self) -> Dict[str, Any]:
        return self.config.get("parent_task_field", {})
    
    @property
    def completion_field(self) -> Dict[str, Any]:
        return self.config.get("completion_field", {})


class NotionService:
    """Handles all Notion-related operations"""
    
    def __init__(self, config: Configuration):
        self.client = NotionClient(auth=config.notion_token)
        self.database_id = config.notion_database_id
        self.config = config
    
    def get_recently_modified_tasks(self) -> List[Dict[str, Any]]:
        """Get tasks modified in the last 5 minutes"""
        now = datetime.now(timezone.utc)
        five_minutes_ago = now - timedelta(minutes=5)
        
        response = self.client.databases.query(
            database_id=self.database_id,
            filter={
                "and": [
                    {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {
                            "after": five_minutes_ago.isoformat()
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


class TodoistService:
    """Handles all Todoist-related operations"""
    
    def __init__(self, config: Configuration):
        # Ensure API patches are applied
        _patch_todoist_api()
        self.client = TodoistAPIAsync(config.todoist_token)
        self._project_id_map = {}
        self._from_notion_label = None
    
    async def initialize(self):
        """Initialize Todoist data that requires async calls"""
        self._project_id_map = await self._get_project_id_map()
        self._from_notion_label = await self._get_or_create_from_notion_label()
    
    async def _get_project_id_map(self) -> Dict[str, str]:
        """Get a mapping of project names to their IDs"""
        try:
            project_map = {}
            projects_result = await self.client.get_projects()
            
            # Handle pagination - consume all pages
            projects = []
            if hasattr(projects_result, '__aiter__'):
                # It's an async generator/iterator
                async for page in projects_result:
                    if isinstance(page, list):
                        projects.extend(page)
                    else:
                        projects.append(page)
            elif hasattr(projects_result, '__iter__') and not isinstance(projects_result, (list, str)):
                # It's a sync iterator/paginator
                for page in projects_result:
                    if isinstance(page, list):
                        projects.extend(page)
                    else:
                        projects.append(page)
            else:
                # It's already a list
                projects = projects_result if isinstance(projects_result, list) else [projects_result]
            
            for project in projects:
                try:
                    project_map[project.name] = project.id
                    print(f"Found project: {project.name} (ID: {project.id})")
                except Exception as e:
                    print(f"Error accessing project data: {e}")
                    continue
            
            print(f"Available Todoist projects: {list(project_map.keys())}")
            return project_map
        except Exception as e:
            print(f"Error getting projects: {e}")
            return {}
    
    async def _get_or_create_from_notion_label(self) -> Optional[str]:
        """Get or create the 'From Notion' label"""
        try:
            labels_result = await self.client.get_labels()
            
            # Handle pagination
            labels = []
            if hasattr(labels_result, '__aiter__'):
                async for page in labels_result:
                    if isinstance(page, list):
                        labels.extend(page)
                    else:
                        labels.append(page)
            elif hasattr(labels_result, '__iter__') and not isinstance(labels_result, (list, str)):
                for page in labels_result:
                    if isinstance(page, list):
                        labels.extend(page)
                    else:
                        labels.append(page)
            else:
                labels = labels_result if isinstance(labels_result, list) else [labels_result]
            
            for label in labels:
                if label.name.lower() == "from notion":
                    print("Found existing 'From Notion' label")
                    return label.name
            
            label = await self.client.add_label(name="From Notion")
            print("Created new 'From Notion' label")
            return label.name
        except Exception as e:
            print(f"Error getting/creating 'From Notion' label: {e}")
            return None
    
    async def get_tasks(self) -> List[Any]:
        """Get all Todoist tasks"""
        tasks_result = await self.client.get_tasks()
        
        # Handle pagination
        tasks = []
        if hasattr(tasks_result, '__aiter__'):
            async for page in tasks_result:
                if isinstance(page, list):
                    tasks.extend(page)
                else:
                    tasks.append(page)
        elif hasattr(tasks_result, '__iter__') and not isinstance(tasks_result, (list, str)):
            for page in tasks_result:
                if isinstance(page, list):
                    tasks.extend(page)
                else:
                    tasks.append(page)
        else:
            tasks = tasks_result if isinstance(tasks_result, list) else [tasks_result]
        
        return tasks
    
    async def get_notion_ids_for_tasks(self, tasks: List[Any]) -> Dict[str, str]:
        """Get Notion IDs for multiple tasks concurrently"""
        # Filter tasks to only those with "From Notion" label
        notion_tasks = [task for task in tasks if any(label.lower() == "from notion" for label in (task.labels or []))]
        print(f"\nFound {len(notion_tasks)} tasks with 'From Notion' label out of {len(tasks)} total tasks")
        
        async def get_task_notion_id(task):
            try:
                comments_result = await self.client.get_comments(task_id=task.id)
                
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
                        return task.id, notion_id
                return task.id, None
            except Exception as e:
                print(f"Error getting comments for task {task.id}: {e}")
                return task.id, None
        
        results = await asyncio.gather(*[get_task_notion_id(task) for task in notion_tasks])
        
        task_notion_map = {}
        for task_id, notion_id in results:
            if notion_id:
                task_notion_map[task_id] = notion_id
        
        print(f"\nTask to Notion ID mapping: {len(task_notion_map)} mappings found")
        return task_notion_map
    
    def find_tasks_by_notion_id(self, tasks: List[Any], notion_id: str, task_notion_map: Dict[str, str]) -> List[Any]:
        """Find all Todoist tasks with the given Notion ID"""
        print(f"\nLooking for tasks with Notion ID: {notion_id}")
        
        matching_tasks = []
        for task in tasks:
            current_id = task_notion_map.get(task.id)
            if current_id == notion_id:
                print(f"Found matching task: {task.id} - {task.content}")
                matching_tasks.append(task)
        
        print(f"Total matching tasks found: {len(matching_tasks)}")
        return matching_tasks
    
    def get_project_id(self, project_name: str) -> Optional[str]:
        """Get project ID by name"""
        return self._project_id_map.get(project_name)
    
    @property
    def from_notion_label(self) -> Optional[str]:
        """Get the 'From Notion' label name"""
        return self._from_notion_label
    
    async def create_task(self, **kwargs) -> Any:
        """Create a new Todoist task"""
        return await self.client.add_task(**kwargs)
    
    async def update_task(self, task_id: str, **kwargs) -> Any:
        """Update an existing Todoist task"""
        return await self.client.update_task(task_id=task_id, **kwargs)
    
    async def complete_task(self, task_id: str):
        """Mark a task as completed"""
        return await self.client.close_task(task_id=task_id)
    
    async def reopen_task(self, task_id: str):
        """Reopen a completed task"""
        return await self.client.reopen_task(task_id=task_id)
    
    async def add_comment(self, task_id: str, content: str):
        """Add a comment to a task"""
        return await self.client.add_comment(task_id=task_id, content=content)
    
    async def delete_task(self, task_id: str):
        """Delete a task"""
        return await self.client.delete_task(task_id=task_id)


class TaskMapper:
    """Handles mapping between Notion and Todoist task fields"""
    
    def __init__(self, config: Configuration):
        self.config = config
    
    def map_notion_to_todoist(self, notion_task: Dict[str, Any]) -> Dict[str, Any]:
        """Map Notion task fields to Todoist fields"""
        todoist_fields = {}
        
        # Process regular field mappings
        for notion_field, todoist_field in self.config.field_mapping.items():
            if notion_field in notion_task["properties"]:
                value = notion_task["properties"][notion_field]
                print(f"Mapping field {notion_field} ({value['type']}) to {todoist_field}")
                
                mapped_value = self._map_field_value(value, todoist_field)
                if mapped_value is not None:
                    todoist_fields[todoist_field] = mapped_value
        
        # Process description fields if enabled
        description = self._build_description(notion_task)
        if description:
            todoist_fields["description"] = description
        
        print(f"Final mapped fields: {todoist_fields}")
        return todoist_fields
    
    def _map_field_value(self, value: Dict[str, Any], todoist_field: str) -> Any:
        """Map a single field value based on its type"""
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


class SyncService:
    """Main service that orchestrates the sync process"""
    
    def __init__(self, config: Configuration):
        self.config = config
        self.notion_service = NotionService(config)
        self.todoist_service = TodoistService(config)
        self.task_mapper = TaskMapper(config)
    
    async def sync(self):
        """Main sync function"""
        print("Starting Notion-Todoist sync...")
        
        try:
            # Initialize services
            await self.todoist_service.initialize()
            
            # Fetch all required data
            notion_tasks = self.notion_service.get_recently_modified_tasks()
            todoist_tasks = await self.todoist_service.get_tasks()
            task_notion_map = await self.todoist_service.get_notion_ids_for_tasks(todoist_tasks)
            
            print(f"Found {len(notion_tasks)} tasks to sync from Notion")
            
            # First pass: Create parent tasks
            parent_tasks_created = await self._create_parent_tasks(notion_tasks, todoist_tasks, task_notion_map)
            
            # Second pass: Process all child tasks
            print(f"\nSecond pass: Processing {len(notion_tasks)} child tasks...")
            results = await asyncio.gather(*[
                self._process_notion_task(
                    task, todoist_tasks, task_notion_map, parent_tasks_created
                )
                for task in notion_tasks
            ])
            
            # Count processed tasks
            processed_count = sum(results)
            print(f"Sync completed. Successfully processed {processed_count}/{len(notion_tasks)} tasks.")
            
        except Exception as e:
            print(f"Sync failed: {e}")
    
    async def _create_parent_tasks(self, notion_tasks: List[Dict[str, Any]], 
                                 todoist_tasks: List[Any], 
                                 task_notion_map: Dict[str, str]) -> Dict[str, str]:
        """Create parent tasks that need to be created"""
        parent_tasks_created = {}
        parent_config = self.config.parent_task_field
        
        if not parent_config or not parent_config.get("create_parent"):
            return parent_tasks_created
        
        print("\nFirst pass: Creating required parent tasks...")
        parent_candidates = {}
        
        # Count how many children each potential parent has
        parent_field = parent_config["name"]
        for task in notion_tasks:
            if parent_field in task["properties"]:
                parent_relation = task["properties"][parent_field]
                if parent_relation["type"] == "relation" and parent_relation["relation"]:
                    parent_page_id = parent_relation["relation"][0]["id"]
                    parent_candidates[parent_page_id] = parent_candidates.get(parent_page_id, 0) + 1
        
        # Create parent tasks for parents with >1 non-completed children
        for parent_page_id, _ in parent_candidates.items():
            existing_parent_id = self._find_existing_parent_task(todoist_tasks, task_notion_map, parent_page_id)
            
            if not existing_parent_id:
                non_completed_count = len(self.notion_service.query_child_tasks(parent_page_id, exclude_completed=True))
                print(f"Parent {parent_page_id} has {non_completed_count} non-completed child tasks")
                
                if non_completed_count >= 1:
                    parent_task_id = await self._create_parent_task(parent_page_id, notion_tasks)
                    if parent_task_id:
                        parent_tasks_created[parent_page_id] = parent_task_id
                        await self._update_existing_children_to_parent(
                            todoist_tasks, task_notion_map, parent_page_id, parent_task_id
                        )
            else:
                # Check if existing parent has the correct project
                correct_project_id = self._determine_parent_project([], parent_page_id)
                if await self._should_recreate_parent_task(existing_parent_id, correct_project_id):
                    # Delete old parent and create new one with correct project
                    new_parent_id = await self._recreate_parent_task(existing_parent_id, parent_page_id, correct_project_id)
                    if new_parent_id:
                        parent_tasks_created[parent_page_id] = new_parent_id
                        await self._update_existing_children_to_parent(
                            todoist_tasks, task_notion_map, parent_page_id, new_parent_id
                        )
                    else:
                        parent_tasks_created[parent_page_id] = existing_parent_id
                else:
                    parent_tasks_created[parent_page_id] = existing_parent_id
                    # Always ensure existing children are moved to the parent
                    await self._update_existing_children_to_parent(
                        todoist_tasks, task_notion_map, parent_page_id, existing_parent_id
                    )
        
        return parent_tasks_created
    
    def _find_existing_parent_task(self, todoist_tasks: List[Any], 
                                 task_notion_map: Dict[str, str], 
                                 parent_page_id: str) -> Optional[str]:
        """Find existing parent task in Todoist"""
        for task in todoist_tasks:
            task_notion_id = task_notion_map.get(task.id)
            if task_notion_id == parent_page_id:
                print(f"Found existing parent task: {task.content} (ID: {task.id})")
                return task.id
        return None
    
    async def _create_parent_task(self, parent_page_id: str, notion_tasks: List[Dict[str, Any]]) -> Optional[str]:
        """Create a new parent task"""
        try:
            parent_config = self.config.parent_task_field
            parent_page = self.notion_service.get_page(parent_page_id)
            title_field = parent_config.get("title_field", "Name")
            parent_title = NotionService.get_field_value(parent_page["properties"].get(title_field))
            
            if not parent_title:
                print(f"Warning: Could not find title in field '{title_field}'")
                parent_title = "Untitled Parent Task"
            
            # Determine the project for the parent task from its children
            parent_project_id = self._determine_parent_project(notion_tasks, parent_page_id)
            
            # Create parent task
            parent_fields = {
                'content': parent_title,
                'labels': [self.todoist_service.from_notion_label] if self.todoist_service.from_notion_label else []
            }
            
            if parent_project_id:
                parent_fields['project_id'] = parent_project_id
            
            parent_task = await self.todoist_service.create_task(**parent_fields)
            await self.todoist_service.add_comment(parent_task.id, f"Notion ID: {parent_page_id}")
            print(f"Created new parent task: {parent_title} (ID: {parent_task.id}) in project: {parent_project_id}")
            
            return parent_task.id
            
        except Exception as e:
            print(f"Error creating parent task for {parent_page_id}: {e}")
            return None
    
    def _determine_parent_project(self, notion_tasks: List[Dict[str, Any]], parent_page_id: str) -> Optional[str]:
        """Determine the project for a parent task based on its children"""
        try:
            # Get all child tasks from Notion (not just the recently modified ones)
            child_notion_tasks = self.notion_service.query_child_tasks(parent_page_id, exclude_completed=False)
            child_projects = set()
            
            # Check all child tasks to find their projects
            for child_task in child_notion_tasks:
                for notion_field, todoist_field in self.config.field_mapping.items():
                    if todoist_field == "project" and notion_field in child_task["properties"]:
                        project_value = child_task["properties"][notion_field]
                        if project_value["type"] == "select" and project_value["select"]:
                            project_name = project_value["select"]["name"]
                            child_projects.add(project_name)
                            print(f"Found child project: {project_name}")
                        elif project_value["type"] == "rich_text" and project_value["rich_text"]:
                            project_name = project_value["rich_text"][0]["plain_text"]
                            child_projects.add(project_name)
                            print(f"Found child project: {project_name}")
            
            if child_projects:
                project_name = list(child_projects)[0]
                project_id = self.todoist_service.get_project_id(project_name)
                print(f"Determined parent project: {project_name} (ID: {project_id})")
                return project_id
                
        except Exception as e:
            print(f"Error determining parent project: {e}")
        
        return None
    
    async def _should_recreate_parent_task(self, parent_task_id: str, correct_project_id: Optional[str]) -> bool:
        """Check if parent task needs to be recreated due to project mismatch"""
        try:
            if not correct_project_id:
                return False
            
            # Get current parent task info
            current_tasks = await self.todoist_service.get_tasks()
            parent_task = next((t for t in current_tasks if t.id == parent_task_id), None)
            
            if not parent_task:
                return False
            
            current_project_id = parent_task.project_id
            needs_recreation = current_project_id != correct_project_id
            
            if needs_recreation:
                print(f"Parent task {parent_task_id} has project {current_project_id}, but should have {correct_project_id}")
                
            return needs_recreation
        except Exception as e:
            print(f"Error checking if parent task needs recreation: {e}")
            return False
    
    async def _recreate_parent_task(self, old_parent_id: str, parent_page_id: str, correct_project_id: str) -> Optional[str]:
        """Delete old parent task and create new one with correct project"""
        try:
            # Get old parent task details
            current_tasks = await self.todoist_service.get_tasks()
            old_parent_task = next((t for t in current_tasks if t.id == old_parent_id), None)
            
            if not old_parent_task:
                print(f"Could not find old parent task {old_parent_id}")
                return None
            
            parent_title = old_parent_task.content
            print(f"Recreating parent task '{parent_title}' with correct project {correct_project_id}")
            
            # Delete old parent task
            await self.todoist_service.delete_task(old_parent_id)
            print(f"Deleted old parent task {old_parent_id}")
            
            # Create new parent task with correct project
            parent_fields = {
                'content': parent_title,
                'project_id': correct_project_id,
                'labels': [self.todoist_service.from_notion_label] if self.todoist_service.from_notion_label else []
            }
            
            new_parent_task = await self.todoist_service.create_task(**parent_fields)
            await self.todoist_service.add_comment(new_parent_task.id, f"Notion ID: {parent_page_id}")
            print(f"Created new parent task: {parent_title} (ID: {new_parent_task.id}) in project: {correct_project_id}")
            
            return new_parent_task.id
            
        except Exception as e:
            print(f"Error recreating parent task: {e}")
            return None
    
    async def _get_parent_task_project(self, parent_task_id: str) -> Optional[str]:
        """Get the project ID of a parent task"""
        try:
            current_tasks = await self.todoist_service.get_tasks()
            parent_task = next((t for t in current_tasks if t.id == parent_task_id), None)
            return parent_task.project_id if parent_task else None
        except Exception as e:
            print(f"Error getting parent task project: {e}")
            return None
    
    async def _delete_and_recreate_task_with_parent(self, task: Any, parent_task_id: str, notion_id: str):
        """Delete existing task and recreate it under the specified parent"""
        try:
            # Store task information before deletion
            task_content = task.content
            task_project_id = await self._get_parent_task_project(parent_task_id)  # Use parent's project
            task_labels = getattr(task, 'labels', []) or []
            task_priority = getattr(task, 'priority', 1)
            task_due = getattr(task, 'due', None)
            
            print(f"Deleting task {task.id}: {task_content}")
            await self.todoist_service.delete_task(task.id)
            
            # Create new task with parent relationship
            create_fields = {
                'content': task_content,
                'parent_id': parent_task_id,
                'labels': task_labels
            }
            
            if task_project_id:
                create_fields['project_id'] = task_project_id
            if task_priority and task_priority > 1:
                create_fields['priority'] = task_priority
            if task_due:
                if hasattr(task_due, 'date'):
                    create_fields['due_date'] = task_due.date
                elif hasattr(task_due, 'string'):
                    create_fields['due_string'] = task_due.string
            
            new_task = await self.todoist_service.create_task(**create_fields)
            await self.todoist_service.add_comment(new_task.id, f"Notion ID: {notion_id}")
            print(f"Successfully recreated task {new_task.id} under parent {parent_task_id}")
            
        except Exception as e:
            print(f"Error in delete and recreate: {e}")
            raise
    
    async def _update_existing_children_to_parent(self, todoist_tasks: List[Any], 
                                                task_notion_map: Dict[str, str], 
                                                parent_page_id: str, 
                                                parent_task_id: str):
        """Update existing child tasks to have the given parent"""
        try:
            child_notion_tasks = self.notion_service.query_child_tasks(parent_page_id, exclude_completed=False)
            print(f"Found {len(child_notion_tasks)} child tasks in Notion for parent {parent_page_id}")
            
            for child_notion_task in child_notion_tasks:
                child_notion_id = child_notion_task["id"]
                matching_tasks = self.todoist_service.find_tasks_by_notion_id(
                    todoist_tasks, child_notion_id, task_notion_map
                )
                
                for task in matching_tasks:
                    try:
                        # Convert to strings for comparison
                        current_parent_id = str(task.parent_id) if task.parent_id else None
                        new_parent_id = str(parent_task_id)
                        
                        if current_parent_id != new_parent_id:
                            print(f"Updating task {task.id} ({task.content}) parent from {current_parent_id} to {new_parent_id}")
                            
                            # First, ensure the child task has the same project as the parent
                            # Get the parent task's project
                            parent_project_id = await self._get_parent_task_project(parent_task_id)
                            if parent_project_id and task.project_id != parent_project_id:
                                print(f"First updating task {task.id} project to match parent: {parent_project_id}")
                                await self.todoist_service.update_task(task.id, project_id=parent_project_id)
                            
                            # Then assign the parent
                            await self.todoist_service.update_task(task.id, parent_id=new_parent_id)
                            print(f"Successfully updated parent relationship for task {task.id}")
                    except Exception as e:
                        print(f"Failed to update parent relationship for {task.id}: {e}")
                        print(f"Error details: {type(e).__name__}: {str(e)}")
                        
                        # If we get a 400 error, try to delete and recreate the task
                        if "400" in str(e):
                            print(f"Attempting to delete and recreate task {task.id} under parent {new_parent_id}")
                            try:
                                await self._delete_and_recreate_task_with_parent(task, new_parent_id, child_notion_id)
                            except Exception as recreate_error:
                                print(f"Failed to delete and recreate task: {recreate_error}")
                        
        except Exception as e:
            print(f"Error updating child tasks: {e}")
    
    async def _process_notion_task(self, notion_task: Dict[str, Any], 
                                 todoist_tasks: List[Any], 
                                 task_notion_map: Dict[str, str], 
                                 parent_tasks_created: Dict[str, str]) -> int:
        """Process a single Notion task and sync it to Todoist"""
        try:
            notion_id = notion_task["id"]
            print(f"Processing Notion task: {notion_id}")
            
            # Map Notion fields to Todoist fields
            todoist_fields = self.task_mapper.map_notion_to_todoist(notion_task)
            
            # Handle project mapping
            project_id = self._get_project_id_from_fields(todoist_fields)
            if project_id:
                todoist_fields["project_id"] = project_id
                todoist_fields.pop("project", None)  # Remove project name
            
            # Check for parent relationship
            parent_task_id = self._get_parent_task_id(notion_task, parent_tasks_created)
            
            # Check completion status
            is_completed = self.task_mapper.is_task_completed(notion_task)
            
            # Find existing Todoist tasks
            matching_tasks = self.todoist_service.find_tasks_by_notion_id(
                todoist_tasks, notion_id, task_notion_map
            )
            
            if not matching_tasks:
                return await self._create_new_task(notion_id, todoist_fields, parent_task_id, is_completed)
            else:
                return await self._update_existing_task(matching_tasks[0], todoist_fields, parent_task_id, is_completed)
                
        except Exception as e:
            print(f"Failed to process Notion task {notion_task.get('id', 'unknown')}: {e}")
            return 0
    
    def _get_project_id_from_fields(self, todoist_fields: Dict[str, Any]) -> Optional[str]:
        """Get project ID from mapped fields"""
        if "project" in todoist_fields:
            project_name = todoist_fields["project"]
            project_id = self.todoist_service.get_project_id(project_name)
            if project_id:
                print(f"Mapped project '{project_name}' to ID: {project_id}")
                return project_id
            else:
                print(f"Warning: Project '{project_name}' not found in Todoist")
        return None
    
    def _get_parent_task_id(self, notion_task: Dict[str, Any], parent_tasks_created: Dict[str, str]) -> Optional[str]:
        """Get parent task ID if applicable"""
        parent_config = self.config.parent_task_field
        if not parent_config or not parent_config.get("create_parent"):
            return None
        
        parent_field = parent_config["name"]
        if parent_field in notion_task["properties"]:
            parent_relation = notion_task["properties"][parent_field]
            if parent_relation["type"] == "relation" and parent_relation["relation"]:
                parent_page_id = parent_relation["relation"][0]["id"]
                parent_task_id = parent_tasks_created.get(parent_page_id)
                if parent_task_id:
                    print(f"Using pre-created parent task ID: {parent_task_id}")
                    return parent_task_id
        return None
    
    async def _create_new_task(self, notion_id: str, todoist_fields: Dict[str, Any],
                             parent_task_id: Optional[str], is_completed: bool) -> int:
        """Create a new Todoist task"""
        if is_completed:
            print(f"Notion task {notion_id} is completed but no matching Todoist task found - doing nothing")
            return 1

        try:
            from datetime import datetime
            create_fields = todoist_fields.copy()
            if parent_task_id:
                create_fields["parent_id"] = parent_task_id

            # Handle due dates - prefer due_date (exact ISO) over due_string (NLP-parsed)
            if "due_date" in create_fields:
                create_fields.pop("due_string", None)
                due_value = create_fields.pop("due_date")
                if isinstance(due_value, str) and "T" in due_value:
                    # Preserve time information — use due_datetime
                    create_fields["due_datetime"] = due_value
                elif isinstance(due_value, str):
                    # Convert string to datetime.date object for the API
                    try:
                        due_date_obj = datetime.strptime(due_value, "%Y-%m-%d").date()
                        create_fields["due_date"] = due_date_obj
                    except ValueError:
                        # If parsing fails, fall back to due_string
                        create_fields["due_string"] = due_value

            # Ensure From Notion label is added
            if "labels" not in create_fields:
                create_fields["labels"] = []
            if self.todoist_service.from_notion_label and self.todoist_service.from_notion_label not in create_fields["labels"]:
                create_fields["labels"].append(self.todoist_service.from_notion_label)

            task = await self.todoist_service.create_task(**create_fields)
            await self.todoist_service.add_comment(task.id, f"Notion ID: {notion_id}")
            print(f"Created new task {task.id} from Notion task {notion_id}")
            return 1
        except Exception as e:
            print(f"Failed to create task from Notion {notion_id}: {e}")
            return 0
    
    async def _update_existing_task(self, task: Any, todoist_fields: Dict[str, Any], 
                                  parent_task_id: Optional[str], is_completed: bool) -> int:
        """Update an existing Todoist task"""
        try:
            # Handle completion status first
            if is_completed and not task.is_completed:
                await self.todoist_service.complete_task(task.id)
                print(f"Marked task {task.id} as completed")
                return 1
            elif not is_completed and task.is_completed:
                await self.todoist_service.reopen_task(task.id)
                print(f"Marked task {task.id} as not completed")
                return 1
            elif is_completed and task.is_completed:
                return 1  # Already in desired state
            
            # Prepare update fields
            update_fields = self._prepare_update_fields(task, todoist_fields)
            
            # Handle parent task relationship
            if parent_task_id:
                current_parent_id = str(task.parent_id) if task.parent_id else None
                new_parent_id = str(parent_task_id)
                if current_parent_id != new_parent_id:
                    update_fields["parent_id"] = new_parent_id
                    print(f"Updating task {task.id} parent to: {new_parent_id}")
            
            # Update the task if there are any changes
            if update_fields:
                try:
                    await self.todoist_service.update_task(task.id, **update_fields)
                    print(f"Updated task {task.id}")
                except Exception as e:
                    print(f"Failed to update task {task.id}: {e}")
                    return 0
            
            return 1
        except Exception as e:
            print(f"Failed to process task {task.id}: {e}")
            return 0
    
    def _prepare_update_fields(self, task: Any, todoist_fields: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare fields for updating a task"""
        from datetime import datetime
        update_fields = {}

        # Handle due dates - prefer due_date (exact ISO) over due_string (NLP-parsed)
        if "due_date" in todoist_fields:
            due_str = todoist_fields["due_date"]
            if isinstance(due_str, str) and "T" in due_str:
                # Preserve time information — use due_datetime
                update_fields["due_datetime"] = due_str
            elif isinstance(due_str, str):
                # Convert string to datetime.date object for the API
                try:
                    due_date_obj = datetime.strptime(due_str, "%Y-%m-%d").date()
                    update_fields["due_date"] = due_date_obj
                except ValueError:
                    # If parsing fails, fall back to due_string
                    update_fields["due_string"] = due_str
        elif "due_string" in todoist_fields:
            update_fields["due_string"] = todoist_fields["due_string"]

        # Handle other fields
        for field in ["content", "description", "priority"]:
            if field in todoist_fields:
                update_fields[field] = todoist_fields[field]
        
        # Handle project update
        if "project_id" in todoist_fields and todoist_fields["project_id"] != task.project_id:
            update_fields["project_id"] = todoist_fields["project_id"]
            print(f"Updating task {task.id} project to: {todoist_fields['project_id']}")
        
        # Handle labels - ensure From Notion label is present
        current_labels = getattr(task, 'labels', []) or []
        if "labels" in todoist_fields:
            labels = todoist_fields["labels"]
        else:
            labels = current_labels.copy()
        
        if self.todoist_service.from_notion_label and self.todoist_service.from_notion_label not in labels:
            labels.append(self.todoist_service.from_notion_label)
        update_fields["labels"] = labels
        
        return update_fields


async def sync():
    """Standalone sync function for backward compatibility"""
    config = Configuration()
    sync_service = SyncService(config)
    await sync_service.sync()


async def main():
    """Main entry point"""
    await sync()


if __name__ == "__main__":
    asyncio.run(main()) 