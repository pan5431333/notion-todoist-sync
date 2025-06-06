from typing import AsyncGenerator, Dict
from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Task, Project, Section, Comment, Label, Collaborator, Attachment
import asyncio

def run_async(func):
    """Run a synchronous function asynchronously in a thread pool."""
    return asyncio.get_event_loop().run_in_executor(None, func)

async def generate_async(iterator):
    """Convert a synchronous iterator to an async generator."""
    for item in iterator:
        yield item

class TodoistAsyncWrapper:
    """
    Async wrapper around the Todoist API.
    """

    def __init__(self, token: str) -> None:
        """Initialize the TodoistAsyncWrapper."""
        self._api = TodoistAPI(token)

    async def __aenter__(self):
        """Enter the async context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context."""
        pass

    async def get_tasks(self) -> AsyncGenerator[list[Task], None]:
        """Get all tasks."""
        tasks = await run_async(self._api.get_tasks)
        yield [tasks] if isinstance(tasks, Task) else tasks

    async def get_projects(self) -> AsyncGenerator[list[Project], None]:
        """Get all projects."""
        projects = await run_async(self._api.get_projects)
        yield [projects] if isinstance(projects, Project) else projects

    async def get_comments(self, task_id: str) -> AsyncGenerator[list[Comment], None]:
        """Get comments for a task."""
        comments = await run_async(lambda: self._api.get_comments(task_id=task_id))
        yield [comments] if isinstance(comments, Comment) else comments

    async def get_labels(self) -> list[Label]:
        """Get all labels."""
        try:
            labels = await run_async(self._api.get_labels)
            # Handle both single label and list of labels
            if isinstance(labels, Label):
                return [labels]
            elif isinstance(labels, list):
                return labels
            else:
                print(f"Warning: Unexpected labels type: {type(labels)}")
                return []
        except Exception as e:
            print(f"Error getting labels: {e}")
            return []

    async def add_label(self, name: str) -> Label:
        """Add a new label."""
        try:
            return await run_async(lambda: self._api.add_label(name=name))
        except Exception as e:
            print(f"Error adding label '{name}': {e}")
            return None

    async def get_all_comments(self) -> Dict[str, str]:
        """
        Get all comments from all tasks and extract Notion IDs.
        Returns a dictionary mapping task IDs to their corresponding Notion IDs.
        """
        task_notion_map = {}
        
        # Get all tasks first
        all_tasks = []
        async for tasks_batch in self.get_tasks():
            all_tasks.extend(tasks_batch)
        
        # Process each task's comments
        for task in all_tasks:
            try:
                async for comments_batch in self.get_comments(task.id):
                    for comment in comments_batch:
                        content = comment.content.strip()
                        if "Notion ID:" in content:
                            notion_id = content.replace("Notion ID:", "").strip()
                            task_notion_map[task.id] = notion_id
                            break  # Found the Notion ID for this task, move to next task
            except Exception as e:
                print(f"Error getting comments for task {task.id}: {e}")
                continue
        
        return task_notion_map

    async def add_task(self, **kwargs) -> Task:
        """Add a new task."""
        return await run_async(lambda: self._api.add_task(**kwargs))

    async def update_task(self, task_id: str, **kwargs) -> Task:
        """Update a task."""
        return await run_async(lambda: self._api.update_task(task_id, **kwargs))

    async def move_task(self, task_id: str, project_id: str = None, parent_id: str = None) -> bool:
        """Move a task to a different project and/or parent."""
        update_args = {}
        if project_id is not None:
            update_args['project_id'] = project_id
        if parent_id is not None:
            update_args['parent_id'] = parent_id
        
        if update_args:
            await self.update_task(task_id, **update_args)
        return True

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        return await run_async(lambda: self._api.delete_task(task_id))

    async def add_comment(self, task_id: str, content: str) -> Comment:
        """Add a comment to a task."""
        return await run_async(lambda: self._api.add_comment(content, task_id=task_id))

    async def close_task(self, task_id: str) -> bool:
        """Close (complete) a task."""
        return await run_async(lambda: self._api.close_task(task_id))

    async def reopen_task(self, task_id: str) -> bool:
        """Reopen (uncomplete) a task."""
        return await run_async(lambda: self._api.reopen_task(task_id)) 