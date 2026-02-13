"""Todoist repository for Notion-Todoist sync"""
import asyncio
from typing import Dict, List, Optional, Any, Tuple

from todoist_api_python.api_async import TodoistAPIAsync

from notion_todoist_sync.config import Configuration


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

        # Also patch the references in api.py (which imports get/post by name)
        import todoist_api_python.api
        todoist_api_python.api.get = _patch_get
        todoist_api_python.api.post = _patch_post

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


class TodoistRepository:
    """Handles all Todoist-related operations"""

    def __init__(self, config: Configuration):
        # Ensure API patches are applied
        _patch_todoist_api()
        self.client = TodoistAPIAsync(config.todoist_token)
        self._project_id_map = {}
        self._from_notion_label = None
        self._labels_map = {}

    async def initialize(self):
        """Initialize Todoist data that requires async calls"""
        self._project_id_map = await self._get_project_id_map()
        self._from_notion_label = await self._get_or_create_from_notion_label()
        self._labels_map = await self._get_labels_map()

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

    async def _get_labels_map(self) -> Dict[str, str]:
        """Get a mapping of label names to their IDs"""
        try:
            labels_map = {}
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
                labels_map[label.name.lower()] = label.id

            return labels_map
        except Exception as e:
            print(f"Error getting labels: {e}")
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

    async def get_task(self, task_id: str) -> Any:
        """Get a specific task by ID"""
        return await self.client.get_task(task_id=task_id)
