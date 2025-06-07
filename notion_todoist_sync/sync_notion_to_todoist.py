import os
import json
import asyncio
import datetime
from notion_client import Client as NotionClient
from todoist_api_python.api_async import TodoistAPIAsync
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
CONFIG_PATH = os.getenv("SYNC_CONFIG_PATH", os.path.join("config", "sync_config.json"))

def load_config(path):
    with open(path, "r") as f:
        return json.load(f)

def get_recently_modified_notion_tasks(notion, database_id):
    now = datetime.now(timezone.utc)
    five_minutes_ago = now - timedelta(minutes=5)
    
    response = notion.databases.query(
        database_id=database_id,
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
                    # Map date field to due_date as fallback
                    if todoist_field == "due_date":
                        todoist_fields["due_date"] = date_str
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
                # Handle rich text fields (for project and due string)
                if value["rich_text"]:
                    text_value = value["rich_text"][0]["plain_text"]
                    if todoist_field == "due_string":
                        # Prioritize due_string over due_date
                        todoist_fields["due_string"] = text_value
                        # Remove due_date if due_string is set
                        todoist_fields.pop("due_date", None)
                    else:
                        todoist_fields[todoist_field] = text_value
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
        projects = await todoist.get_projects()
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

async def get_or_create_from_notion_label(todoist):
    """Get or create the 'From Notion' label"""
    try:
        # Get all labels
        labels = await todoist.get_labels()
        for label in labels:
            if label.name.lower() == "from notion":
                print("Found existing 'From Notion' label")
                return label.name
        
        # Create the label if it doesn't exist
        label = await todoist.add_label(name="From Notion")
        print("Created new 'From Notion' label")
        return label.name
    except Exception as e:
        print(f"Error getting/creating 'From Notion' label: {e}")
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
    
    # Filter tasks to only those with "From Notion" label
    notion_tasks = [task for task in flat_tasks if any(label.lower() == "from notion" for label in (task.labels or []))]
    print(f"\nFound {len(notion_tasks)} tasks with 'From Notion' label out of {len(flat_tasks)} total tasks")
    
    # Get all task-notion ID mappings for filtered tasks
    task_notion_map = {}
    for task in notion_tasks:
        try:
            comments = await todoist.get_comments(task_id=task.id)
            for comment in comments:
                content = comment.content.strip()
                if "Notion ID:" in content:
                    notion_id = content.replace("Notion ID:", "").strip()
                    task_notion_map[task.id] = notion_id
                    break  # Found the Notion ID for this task, move to next task
        except Exception as e:
            print(f"Error getting comments for task {task.id}: {e}")
            continue
    
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

async def sync_parent_task_metadata(todoist, parent_task, child_task):
    """Sync parent task metadata (parent ID and due dates) between tasks"""
    try:
        # Only update if the parent ID has changed
        if child_task.parent_id != parent_task.id:
            print(f"\nUpdating parent ID for task {child_task.id} to {parent_task.id}")
            try:
                # First move the task to the same project as the parent
                if child_task.project_id != parent_task.project_id:
                    await todoist.update_task(
                        task_id=child_task.id,
                        project_id=parent_task.project_id
                    )
                    print(f"Moved task to parent's project: {parent_task.project_id}")
                
                # Then update the parent ID
                await todoist.update_task(
                    task_id=child_task.id,
                    parent_id=parent_task.id
                )
                print(f"Successfully updated parent ID to: {parent_task.id}")
            except Exception as e:
                print(f"Error updating parent relationship: {e}")
                print("Task must be in the same project as its parent. Ensure both tasks are in the same project.")
        else:
            print(f"Parent ID already set correctly for task {child_task.id}")

        # Update parent task's due date if child's due date is later
        try:
            child_due = getattr(child_task, 'due', None)
            parent_due = getattr(parent_task, 'due', None)
            
            if child_due and child_due.date:
                child_date = datetime.fromisoformat(child_due.date).date()
                parent_date = datetime.fromisoformat(parent_due.date).date() if parent_due and parent_due.date else None
                
                if not parent_date or child_date > parent_date:
                    print(f"\nUpdating parent task due date from {parent_date} to {child_date}")
                    await todoist.update_task(
                        task_id=parent_task.id,
                        due_date=child_date.isoformat()
                    )
                    print(f"Successfully updated parent task due date to {child_date}")
        except Exception as e:
            print(f"Error updating parent task due date: {e}")

    except Exception as e:
        print(f"Error in sync_parent_task_metadata: {e}")

async def get_or_create_parent_task(todoist, notion, notion_task, config, project_id_map, task_notion_map, from_notion_label=None):
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
    parent_task = None
    tasks = await todoist.get_tasks()
    for task in tasks:
        task_notion_id = task_notion_map.get(task.id)
        if task_notion_id == parent_page_id:
            print(f"Found existing parent task: {task.content} (ID: {task.id})")
            parent_task = task
            # Update the title if it has changed
            if task.content != parent_title:
                await todoist.update_task(task_id=task.id, content=parent_title)
                print(f"Updated parent task title to: {parent_title}")
            
            # Add "From Notion" label if it's missing
            if from_notion_label and from_notion_label not in (task.labels or []):
                labels = list(task.labels or [])
                labels.append(from_notion_label)
                await todoist.update_task(task_id=task.id, labels=labels)
                print(f"Added 'From Notion' label to parent task")
            
            return task.id

    # If no parent task exists, create one
    if parent_config.get("create_parent"):
        # Get the project ID from the child task's project
        project_name = get_notion_field_value(notion_task["properties"].get("项目"))
        project_id = project_id_map.get(project_name) if project_name else None

        # Prepare task fields
        task_fields = {
            'content': parent_title,
            'project_id': project_id if project_id else None,
        }
        
        # Add "From Notion" label if available
        if from_notion_label:
            task_fields['labels'] = [from_notion_label]
        
        # Create parent task
        parent_task = await todoist.add_task(**task_fields)
        # Add Notion ID as comment
        await todoist.add_comment(task_id=parent_task.id, content=f"Notion ID: {parent_page_id}")
        print(f"Created new parent task: {parent_task.content} (ID: {parent_task.id})")
        return parent_task.id

    return None

async def sync():
    """Main sync function"""
    print("Starting sync function...")
    notion = NotionClient(auth=NOTION_TOKEN)
    todoist = TodoistAPIAsync(TODOIST_TOKEN)
    
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
        all_todoist_tasks = await todoist.get_tasks()
        print(f"Retrieved {len(all_todoist_tasks)} tasks from Todoist")
        
        # Get project name to ID mapping
        project_id_map = await get_todoist_project_id_map(todoist)
        print(f"Retrieved {len(project_id_map)} projects from Todoist")
        
        # Get or create "From Notion" label
        from_notion_label = await get_or_create_from_notion_label(todoist)
        if not from_notion_label:
            print("Failed to get/create 'From Notion' label, continuing without it")
        
        # Get all task-notion ID mappings
        task_notion_map = await get_notion_ids_for_tasks(todoist, all_todoist_tasks)
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
            
            # Add "From Notion" label if available
            if from_notion_label:
                labels = valid_fields.get('labels', [])
                if from_notion_label not in labels:
                    labels.append(from_notion_label)
                valid_fields['labels'] = labels
            
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
            parent_id = await get_or_create_parent_task(todoist, notion, notion_task, config, project_id_map, task_notion_map, from_notion_label)
            if parent_id:
                valid_fields['parent_id'] = parent_id
                print(f"Task will be created as subtask of: {parent_id}")
                
                # Get parent task object for metadata sync
                parent_task = None
                tasks = await todoist.get_tasks()
                for task in tasks:
                    if task.id == parent_id:
                        parent_task = task
                        break
            
            # Find all tasks with this Notion ID
            matching_tasks = []
            for task in all_todoist_tasks:
                task_notion_id = task_notion_map.get(task.id)
                if task_notion_id == notion_id:
                    matching_tasks.append(task)
            
            # Check completion status
            completion_config = config.get("completion_field")
            is_completed = False
            if completion_config:
                field_name = completion_config["name"]
                done_value = completion_config["done_value"]
                if field_name in notion_task["properties"]:
                    status = notion_task["properties"][field_name]
                    print(f"\nChecking completion status:")
                    print(f"Field name: {field_name}")
                    print(f"Done value: {done_value}")
                    print(f"Current status: {status}")
                    if status["type"] == "status" and status["status"]:
                        current_value = status["status"]["name"]
                        is_completed = current_value == done_value
                        print(f"Task completion status: {is_completed} (Notion value: {current_value}, Done value: {done_value})")
            
            if matching_tasks:
                print(f"\nFound {len(matching_tasks)} tasks with Notion ID: {notion_id}")
                print("Matching tasks:")
                for task in matching_tasks:
                    print(f"- Task ID: {task.id}, Content: {task.content}, Is Completed: {task.is_completed}")
                
                # Update the first task
                first_task = matching_tasks[0]
                try:
                    update_fields = {}
                    
                    # Handle completion status first
                    if is_completed and not first_task.is_completed:
                        print(f"\nMarking task {first_task.id} as completed (current status: {first_task.is_completed})")
                        await todoist.close_task(task_id=first_task.id)
                        print(f"Successfully marked task {first_task.id} as completed")
                        processed_count += 1
                        continue  # Skip other updates if task is completed
                    elif not is_completed and first_task.is_completed:
                        print(f"\nMarking task {first_task.id} as not completed (current status: {first_task.is_completed})")
                        await todoist.reopen_task(task_id=first_task.id)
                        print(f"Successfully marked task {first_task.id} as not completed")
                    elif is_completed and first_task.is_completed:
                        print(f"\nTask {first_task.id} is already completed, skipping updates")
                        processed_count += 1
                        continue  # Skip other updates if task is already completed
                    
                    # Handle due dates
                    if "due_string" in valid_fields:
                        # Always use due_string if it's available
                        update_fields["due_string"] = valid_fields["due_string"]
                        print(f"Setting due string to: {valid_fields['due_string']}")
                    elif "due_date" in valid_fields:
                        # Fall back to due_date if no due_string is available
                        due_str = valid_fields["due_date"]
                        if "T" in due_str:  # ISO format with time
                            due_str = due_str.split("T")[0]  # Keep only the date part
                        update_fields["due_date"] = due_str
                        print(f"Setting due date to: {due_str}")
                    
                    if "content" in valid_fields:
                        update_fields["content"] = valid_fields["content"]
                    
                    if "description" in valid_fields:
                        update_fields["description"] = valid_fields["description"]
                    
                    if "priority" in valid_fields:
                        update_fields["priority"] = valid_fields["priority"]
                    
                    if "project" in valid_fields and valid_fields["project"] in project_id_map:
                        project_id = project_id_map[valid_fields["project"]]
                        if project_id != first_task.project_id:
                            update_fields["project_id"] = project_id
                    
                    # Update labels if needed
                    if "labels" in valid_fields:
                        labels = valid_fields["labels"]
                        if from_notion_label and from_notion_label not in labels:
                            labels.append(from_notion_label)
                        update_fields["labels"] = labels
                    
                    # Update the task if there are any changes
                    if update_fields:
                        print(f"\nUpdating task {first_task.id} with fields: {update_fields}")
                        try:
                            await todoist.update_task(task_id=first_task.id, **update_fields)
                            print(f"Successfully updated task {first_task.id}")
                            processed_count += 1
                        except Exception as e:
                            print(f"Error updating task {first_task.id}: {e}")
                            print(f"Update fields that failed: {update_fields}")
                    else:
                        print(f"\nNo updates needed for task {first_task.id}")
                    
                    # Handle parent task relationship after other updates
                    if parent_task:
                        try:
                            await sync_parent_task_metadata(todoist, parent_task, first_task)
                        except Exception as e:
                            print(f"Error updating parent task relationship: {e}")
                
                except Exception as e:
                    print(f"Error processing task {first_task.id}: {e}")
                    continue
                
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
                    # Convert project name to project_id for new task
                    if 'project' in valid_fields:
                        project_name = valid_fields.pop('project')
                        if project_name in project_id_map:
                            valid_fields['project_id'] = project_id_map[project_name]
                    
                    # Convert due_string to due_date if needed
                    if 'due_string' in valid_fields:
                        due_string = valid_fields.pop('due_string')
                        valid_fields['due_date'] = due_string
                    
                    new_task = await todoist.add_task(**valid_fields)
                    # Add Notion ID as a comment
                    await todoist.add_comment(task_id=new_task.id, content=f"Notion ID: {notion_id}")
                    print(f"Created new task: {valid_fields.get('content')} with Notion ID: {notion_id}")
                    
                    # Handle completion status for new task
                    if is_completed:
                        await todoist.complete_task(task_id=new_task.id)
                        print(f"Marked new task {new_task.id} as completed")
                    
                    # Sync parent task metadata if needed
                    if parent_task:
                        await sync_parent_task_metadata(todoist, parent_task, new_task)
                    
                    processed_count += 1
                except Exception as e:
                    print(f"Failed to process task: {valid_fields}, error: {str(e)}")
                    
        except Exception as e:
            print(f"Error processing Notion task: {e}")
            continue
    
    print(f"\nSync completed. Processed {processed_count} tasks.")

if __name__ == "__main__":
    asyncio.run(sync()) 