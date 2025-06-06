import os
import json
import asyncio
import datetime
from notion_client import Client as NotionClient
from todoist_async_wrapper import TodoistAsyncWrapper
from dotenv import load_dotenv
from datetime import datetime, date, timezone, timedelta

print("Starting sync script...")

load_dotenv()
print("Loaded environment variables")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
TODOIST_TOKEN = os.getenv("TODOIST_TOKEN")

print(f"Notion Token exists: {bool(NOTION_TOKEN)}")
print(f"Notion Database ID exists: {bool(NOTION_DATABASE_ID)}")
print(f"Todoist Token exists: {bool(TODOIST_TOKEN)}")

# Example config: {"notion_column_name": "todoist_field_name", ...}
CONFIG_PATH = os.getenv("SYNC_CONFIG_PATH", "sync_config.json")

def load_config(path):
    with open(path, "r") as f:
        return json.load(f)

def get_recently_modified_notion_tasks(notion, database_id):
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    
    response = notion.databases.query(
        database_id=database_id,
        filter={
            "and": [
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {
                        "after": one_hour_ago.isoformat()
                    }
                }
            ]
        }
    )
    
    return response["results"]

def map_notion_to_todoist(notion_task, config):
    """Map Notion task fields to Todoist fields"""
    todoist_fields = {}
    
    # Get field mapping from config
    field_mapping = config.get("field_mapping", {})
    
    # Process regular field mappings
    for notion_field, todoist_field in field_mapping.items():
        if notion_field in notion_task["properties"]:
            value = notion_task["properties"][notion_field]
            print(f"Mapping field {notion_field} ({value['type']}) to {todoist_field}")
            
            # Handle different Notion field types
            if value["type"] == "title":
                if value["title"]:
                    todoist_fields[todoist_field] = value["title"][0]["plain_text"]
            elif value["type"] == "date":
                if value["date"]:
                    date_str = value["date"]["start"]
                    # Convert Notion date to Todoist due_string format
                    if todoist_field == "due_date":
                        todoist_fields["due_string"] = date_str
                    else:
                        todoist_fields[todoist_field] = date_str
            elif value["type"] == "select":
                if value["select"]:
                    # Convert priority strings to integers (3 -> 2, 2 -> 3, 1 -> 4)
                    if todoist_field == "priority":
                        priority_value = value["select"]["name"]
                        try:
                            # Convert string number to int and map to Todoist priority
                            notion_priority = int(priority_value)
                            # In Notion: 1 is highest, 3 is lowest
                            # In Todoist: 4 is highest, 1 is lowest
                            priority_map = {1: 4, 2: 3, 3: 2, 4: 1}
                            todoist_fields[todoist_field] = priority_map.get(notion_priority, 1)
                        except (ValueError, TypeError):
                            # If priority is not a number, use default priority
                            todoist_fields[todoist_field] = 1
                        print(f"Priority mapping: Notion {priority_value} -> Todoist {todoist_fields[todoist_field]}")
                    else:
                        todoist_fields[todoist_field] = value["select"]["name"]
            elif value["type"] == "rich_text":
                # Handle rich text fields (for project)
                if value["rich_text"]:
                    todoist_fields[todoist_field] = value["rich_text"][0]["plain_text"]
                    if todoist_field == "project":
                        print(f"Project from Notion: {todoist_fields[todoist_field]}")
            elif value["type"] == "multi_select":
                # Handle multi-select fields (for labels)
                if value["multi_select"]:
                    todoist_fields[todoist_field] = [item["name"] for item in value["multi_select"]]
            elif value["type"] == "rich_text":
                # Handle due string text
                if value["rich_text"]:
                    if todoist_field == "due_string":
                        todoist_fields[todoist_field] = value["rich_text"][0]["plain_text"]
    
    # Process description fields if enabled
    description_config = config.get("description_fields", {})
    if description_config.get("enabled", False):
        description_parts = []
        
        for field_config in description_config.get("fields", []):
            field_name = field_config["name"]
            if field_name in notion_task["properties"]:
                value = notion_task["properties"][field_name]
                field_content = ""
                
                # Extract the value based on field type
                if value["type"] == "rich_text" and value["rich_text"]:
                    field_content = value["rich_text"][0]["plain_text"]
                elif value["type"] == "select" and value["select"]:
                    field_content = value["select"]["name"]
                elif value["type"] == "multi_select" and value["multi_select"]:
                    field_content = ", ".join(item["name"] for item in value["multi_select"])
                elif value["type"] == "date" and value["date"]:
                    field_content = value["date"]["start"]
                elif value["type"] == "checkbox":
                    field_content = "Yes" if value["checkbox"] else "No"
                elif value["type"] == "number":
                    field_content = str(value["number"]) if value["number"] is not None else ""
                
                # Only add non-empty fields
                if field_content:
                    formatted_content = field_config["format"].format(value=field_content)
                    description_parts.append(formatted_content)
        
        # Combine all parts with the specified separator
        if description_parts:
            separator = description_config.get("separator", "\n\n")
            todoist_fields["description"] = separator.join(description_parts)
            print(f"Added description from fields: {[f['name'] for f in description_config['fields']]}")
    
    print(f"Final mapped fields: {todoist_fields}")
    return todoist_fields

async def get_todoist_project_id_map(todoist):
    """Get a mapping of project names to their IDs"""
    try:
        project_map = {}
        
        # Get projects using the async API
        async for projects_batch in todoist.get_projects():
            for project in projects_batch:
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

async def get_notion_id_from_comments(todoist, task):
    """Extract Notion ID from task comments if it exists"""
    try:
        # Get comments using the async API
        async for comments_batch in todoist.get_comments(task_id=task.id):
            for comment in comments_batch:
                content = comment.content.strip()
                if "Notion ID:" in content:
                    notion_id = content.replace("Notion ID:", "").strip()
                    print(f"Found Notion ID: '{notion_id}' for task {task.id}")
                    return notion_id
    except Exception as e:
        task_id = getattr(task, 'id', 'unknown')
        print(f"Error getting comments for task {task_id}: {e}")
    return None

async def get_notion_ids_for_tasks(todoist, tasks):
    """Get Notion IDs for multiple tasks concurrently"""
    tasks_list = list(tasks) if hasattr(tasks, '__iter__') else [tasks]
    flat_tasks = []
    
    # Flatten nested lists of tasks
    for task in tasks_list:
        if isinstance(task, list):
            flat_tasks.extend(task)
        else:
            flat_tasks.append(task)
    
    # Get all task-notion ID mappings at once
    task_notion_map = await todoist.get_all_comments()
    
    # Debug print
    print("\nTask to Notion ID mapping:")
    for task_id, notion_id in task_notion_map.items():
        print(f"Task {task_id} -> Notion ID: '{notion_id}'")
    
    return task_notion_map

async def find_tasks_by_notion_id(todoist, tasks, notion_id, task_notion_map):
    """Find all Todoist tasks with the given Notion ID"""
    if not tasks:
        return []
    
    print(f"\nLooking for tasks with Notion ID: {notion_id}")
    
    # Find tasks with matching Notion ID
    matching_tasks = []
    for task in tasks:
        if isinstance(task, list):
            for t in task:
                current_id = task_notion_map.get(t.id)
                if current_id == notion_id:
                    print(f"Found matching task: {t.id} - {t.content}")
                    matching_tasks.append(t)
        else:
            current_id = task_notion_map.get(task.id)
            if current_id == notion_id:
                print(f"Found matching task: {task.id} - {task.content}")
                matching_tasks.append(task)
    
    print(f"Total matching tasks found: {len(matching_tasks)}")
    if matching_tasks:
        print("Matching tasks:")
        for task in matching_tasks:
            print(f"- Task ID: {task.id}, Content: {task.content}")
    
    return matching_tasks

def get_notion_field_value(field_value):
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

async def get_or_create_parent_task(todoist, notion, notion_task, config, project_id_map, task_notion_map):
    """Get or create a parent task based on the parent field value"""
    parent_config = config.get("parent_task_field")
    if not parent_config or not parent_config.get("create_parent"):
        return None

    parent_field = parent_config["name"]
    if parent_field not in notion_task["properties"]:
        return None

    parent_relation = notion_task["properties"][parent_field]
    if parent_relation["type"] != "relation" or not parent_relation["relation"]:
        return None

    parent_page_id = parent_relation["relation"][0]["id"]
    if not parent_page_id:
        return None

    print(f"\nLooking for parent task with page ID: {parent_page_id}")

    # Get the parent page title from Notion
    try:
        parent_page = notion.pages.retrieve(parent_page_id)
        title_field = parent_config.get("title_field", "Name")  # Default to "Name" if not specified
        parent_title = get_notion_field_value(parent_page["properties"].get(title_field))
        
        if not parent_title:
            print(f"Warning: Could not find title in field '{title_field}', parent page properties: {list(parent_page['properties'].keys())}")
            parent_title = "Untitled Parent Task"
        
        print(f"Found parent page title: {parent_title}")
    except Exception as e:
        print(f"Error fetching parent page: {e}")
        return None

    # Search for existing parent task with this Notion ID
    async for tasks_batch in todoist.get_tasks():
        for task in tasks_batch:
            task_notion_id = task_notion_map.get(task.id)
            if task_notion_id == parent_page_id:
                print(f"Found existing parent task: {task.content} (ID: {task.id})")
                # Update the title if it has changed
                if task.content != parent_title:
                    await todoist.update_task(task_id=task.id, content=parent_title)
                    print(f"Updated parent task title to: {parent_title}")
                return task.id

    # If no parent task exists, create one
    if parent_config.get("create_parent"):
        # Get the project ID from the child task's project
        project_name = get_notion_field_value(notion_task["properties"].get("项目"))
        project_id = project_id_map.get(project_name) if project_name else None

        # Create parent task
        parent_task = await todoist.add_task(
            content=parent_title,
            project_id=project_id if project_id else None
        )
        # Add Notion ID as comment
        await todoist.add_comment(task_id=parent_task.id, content=f"Notion ID: {parent_page_id}")
        print(f"Created new parent task: {parent_task.content} (ID: {parent_task.id})")
        return parent_task.id

    return None

async def sync():
    print("Starting sync function...")
    notion = NotionClient(auth=NOTION_TOKEN)
    async with TodoistAsyncWrapper(TODOIST_TOKEN) as todoist:
        try:
            config = load_config(CONFIG_PATH)
            print("Loaded config from sync_config.json")
        except Exception as e:
            print(f"Error loading config: {e}")
            return
        
        try:
            notion_tasks = get_recently_modified_notion_tasks(notion, NOTION_DATABASE_ID)
            print(f"Retrieved {len(notion_tasks)} tasks from Notion")
            if not notion_tasks:  # Early return if no tasks to process
                print("No tasks to sync from Notion")
                return
        except Exception as e:
            print(f"Error getting Notion tasks: {e}")
            return
        
        # Get all Todoist tasks and task-notion ID mappings once
        try:
            all_todoist_tasks = []
            async for tasks_batch in todoist.get_tasks():
                all_todoist_tasks.extend(tasks_batch)
            print(f"Retrieved {len(all_todoist_tasks)} tasks from Todoist")
            
            # Get project name to ID mapping
            project_id_map = await get_todoist_project_id_map(todoist)
            print(f"Retrieved {len(project_id_map)} projects from Todoist")
            
            # Get all task-notion ID mappings
            task_notion_map = await todoist.get_all_comments()
            print(f"Retrieved Notion IDs for {len(task_notion_map)} tasks")
            
        except Exception as e:
            print(f"Error getting Todoist tasks or projects: {e}")
            return
        
        processed_count = 0
        for notion_task in notion_tasks:
            try:
                # Get Notion task ID
                notion_id = notion_task["id"]
                print(f"\nProcessing Notion task: {notion_id}")
                
                # Map Notion task fields to Todoist fields
                valid_fields = map_notion_to_todoist(notion_task, config)
                
                if not valid_fields.get('content'):
                    print("Skipping task with no content")
                    continue
                
                # Convert project name to project_id if present
                if 'project' in valid_fields:
                    project_name = valid_fields.pop('project')
                    print(f"Looking up project ID for: {project_name}")
                    if project_name in project_id_map:
                        valid_fields['project_id'] = project_id_map[project_name]
                        print(f"Found project ID: {valid_fields['project_id']}")
                    else:
                        print(f"Warning: Project '{project_name}' not found in Todoist")
                
                # Get or create parent task if needed
                parent_id = await get_or_create_parent_task(todoist, notion, notion_task, config, project_id_map, task_notion_map)
                if parent_id:
                    valid_fields['parent_id'] = parent_id
                    print(f"Task will be created as subtask of: {parent_id}")
                
                # Find all tasks with this Notion ID
                matching_tasks = await find_tasks_by_notion_id(todoist, all_todoist_tasks, notion_id, task_notion_map)
                
                if matching_tasks:
                    print(f"\nFound {len(matching_tasks)} tasks with Notion ID: {notion_id}")
                    print("Matching tasks:")
                    for task in matching_tasks:
                        print(f"- Task ID: {task.id}, Content: {task.content}")
                    
                    # Update the first task
                    first_task = matching_tasks[0]
                    try:
                        # For update_task, we need to handle project_id and parent_id separately
                        if 'project_id' in valid_fields:
                            # Move the task to the new project first
                            await todoist.move_task(task_id=first_task.id, project_id=valid_fields.pop('project_id'))
                        
                        # Handle parent_id separately
                        if 'parent_id' in valid_fields:
                            parent_id = valid_fields.pop('parent_id')
                            await todoist.move_task(task_id=first_task.id, parent_id=parent_id)
                        
                        # Now update the other fields
                        await todoist.update_task(task_id=first_task.id, **valid_fields)
                        print(f"Updated task: {first_task.id} - {valid_fields.get('content')}")
                        processed_count += 1
                    except Exception as e:
                        print(f"Error updating task {first_task.id}: {e}")
                    
                    # Delete any duplicates
                    if len(matching_tasks) > 1:
                        print(f"\nDeleting {len(matching_tasks) - 1} duplicate tasks:")
                        for duplicate in matching_tasks[1:]:
                            try:
                                print(f"Deleting duplicate task: {duplicate.id} - {duplicate.content}")
                                await todoist.delete_task(task_id=duplicate.id)
                                print(f"Successfully deleted task: {duplicate.id}")
                            except Exception as e:
                                print(f"Error deleting duplicate task {duplicate.id}: {e}")
                else:
                    # Create new task
                    try:
                        new_task = await todoist.add_task(**valid_fields)
                        # Add Notion ID as a comment
                        await todoist.add_comment(task_id=new_task.id, content=f"Notion ID: {notion_id}")
                        print(f"Created new task: {valid_fields.get('content')} with Notion ID: {notion_id}")
                        processed_count += 1
                    except Exception as e:
                        print(f"Failed to process task: {valid_fields}, error: {str(e)}")
                        
            except Exception as e:
                print(f"Error processing Notion task: {e}")
                continue
        
        print(f"\nSync completed. Processed {processed_count} tasks.")

if __name__ == "__main__":
    asyncio.run(sync()) 