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
                    elif todoist_field == "project":
                        todoist_fields[todoist_field] = text_value
                        print(f"Project from Notion: {text_value}")
                    else:
                        todoist_fields[todoist_field] = text_value
            elif value["type"] == "multi_select":
                # Handle multi-select fields (for labels)
                if value["multi_select"]:
                    todoist_fields[todoist_field] = [item["name"] for item in value["multi_select"]]
    
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
    
    # Get all task-notion ID mappings for filtered tasks concurrently
    task_notion_map = {}
    
    async def get_task_notion_id(task):
        """Helper function to get Notion ID for a single task"""
        try:
            comments = await todoist.get_comments(task_id=task.id)
            for comment in comments:
                content = comment.content.strip()
                if "Notion ID:" in content:
                    notion_id = content.replace("Notion ID:", "").strip()
                    return task.id, notion_id
            return task.id, None
        except Exception as e:
            print(f"Error getting comments for task {task.id}: {e}")
            return task.id, None
    
    # Gather all comment fetching coroutines
    results = await asyncio.gather(*[get_task_notion_id(task) for task in notion_tasks])
    
    # Process results
    for task_id, notion_id in results:
        if notion_id:
            task_notion_map[task_id] = notion_id
    
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

async def sync():
    """Main sync function"""
    print("Starting Notion-Todoist sync...")
    
    try:
        # Load config and initialize clients
        config = load_config(CONFIG_PATH)
        notion = NotionClient(auth=NOTION_TOKEN)
        todoist = TodoistAPIAsync(TODOIST_TOKEN)
        
        # Fetch all required data
        notion_tasks = get_recently_modified_notion_tasks(notion, NOTION_DATABASE_ID)
        todoist_tasks = await todoist.get_tasks()
        project_id_map = await get_todoist_project_id_map(todoist)
        from_notion_label = await get_or_create_from_notion_label(todoist)
        task_notion_map = await get_notion_ids_for_tasks(todoist, todoist_tasks)
        
        print(f"Found {len(notion_tasks)} tasks to sync from Notion")
        
        # First pass: Create parent tasks that need to be created
        parent_tasks_created = {}  # parent_page_id -> todoist_task_id
        parent_config = config.get("parent_task_field")
        
        if parent_config and parent_config.get("create_parent"):
            print("\nFirst pass: Creating required parent tasks...")
            parent_candidates = {}  # parent_page_id -> count
            
            # Count how many children each potential parent has
            for task in notion_tasks:
                parent_field = parent_config["name"]
                if parent_field in task["properties"]:
                    parent_relation = task["properties"][parent_field]
                    if parent_relation["type"] == "relation" and parent_relation["relation"]:
                        parent_page_id = parent_relation["relation"][0]["id"]
                        parent_candidates[parent_page_id] = parent_candidates.get(parent_page_id, 0) + 1
            
            # Create parent tasks for parents with >1 non-completed children
            for parent_page_id, _ in parent_candidates.items():
                # Check if parent already exists in Todoist
                existing_parent_id = None
                for task in todoist_tasks:
                    task_notion_id = task_notion_map.get(task.id)
                    if task_notion_id == parent_page_id:
                        existing_parent_id = task.id
                        print(f"Found existing parent task: {task.content} (ID: {task.id})")
                        break
                
                if not existing_parent_id:
                    # Count non-completed children from Notion
                    non_completed_count = await count_non_completed_child_tasks(notion, parent_page_id, config)
                    print(f"Parent {parent_page_id} has {non_completed_count} non-completed child tasks")
                    
                    if non_completed_count > 1:
                        try:
                            # Get parent page details
                            parent_page = notion.pages.retrieve(parent_page_id)
                            title_field = parent_config.get("title_field", "Name")
                            parent_title = get_notion_field_value(parent_page["properties"].get(title_field))
                            
                            if not parent_title:
                                print(f"Warning: Could not find title in field '{title_field}'")
                                parent_title = "Untitled Parent Task"
                            
                            # Create parent task
                            parent_fields = {
                                'content': parent_title,
                                'labels': [from_notion_label] if from_notion_label else []
                            }
                            
                            # Add project if available
                            default_project = project_id_map.get(list(project_id_map.keys())[0]) if project_id_map else None
                            if default_project:
                                parent_fields['project_id'] = default_project
                            
                            parent_task = await todoist.add_task(**parent_fields)
                            await todoist.add_comment(task_id=parent_task.id, content=f"Notion ID: {parent_page_id}")
                            parent_tasks_created[parent_page_id] = parent_task.id
                            print(f"Created new parent task: {parent_title} (ID: {parent_task.id})")
                        except Exception as e:
                            print(f"Error creating parent task for {parent_page_id}: {e}")
                else:
                    parent_tasks_created[parent_page_id] = existing_parent_id
        
        # Second pass: Process all child tasks
        print(f"\nSecond pass: Processing {len(notion_tasks)} child tasks...")
        results = await asyncio.gather(*[
            process_notion_task_with_parents(
                task,
                notion,
                todoist,
                config,
                project_id_map,
                task_notion_map,
                from_notion_label,
                parent_tasks_created,
                todoist_tasks  # Pass cached todoist tasks
            )
            for task in notion_tasks
        ])
        
        # Count processed tasks
        processed_count = sum(results)
        print(f"Sync completed. Successfully processed {processed_count}/{len(notion_tasks)} tasks.")
        
    except Exception as e:
        print(f"Sync failed: {e}")

async def process_notion_task_with_parents(notion_task, notion, todoist, config, project_id_map, task_notion_map, from_notion_label, parent_tasks_created, cached_todoist_tasks):
    """Process a single Notion task and sync it to Todoist with pre-created parents"""
    try:
        notion_id = notion_task["id"]
        print(f"Processing Notion task: {notion_id}")
        
        # Map Notion fields to Todoist fields
        todoist_fields = map_notion_to_todoist(notion_task, config)
        
        # Look up project ID if needed
        project_id = None
        if "project" in todoist_fields:
            project_name = todoist_fields.pop("project")  # Remove project name and store project_id instead
            if project_name in project_id_map:
                project_id = project_id_map[project_name]
                todoist_fields["project_id"] = project_id
                print(f"Mapped project '{project_name}' to ID: {project_id}")
            else:
                print(f"Warning: Project '{project_name}' not found in Todoist")
        
        # Check for parent relationship
        parent_task_id = None
        parent_config = config.get("parent_task_field")
        if parent_config and parent_config.get("create_parent"):
            parent_field = parent_config["name"]
            if parent_field in notion_task["properties"]:
                parent_relation = notion_task["properties"][parent_field]
                if parent_relation["type"] == "relation" and parent_relation["relation"]:
                    parent_page_id = parent_relation["relation"][0]["id"]
                    parent_task_id = parent_tasks_created.get(parent_page_id)
                    if parent_task_id:
                        print(f"Using pre-created parent task ID: {parent_task_id}")
        
        # Check completion status
        is_completed = False
        if "completion_field" in config:
            field_name = config["completion_field"]["name"]
            done_value = config["completion_field"]["done_value"]
            if field_name in notion_task["properties"]:
                current_status = notion_task["properties"][field_name]
                if current_status["type"] == "status":
                    is_completed = current_status["status"]["name"] == done_value
        
        # Find existing Todoist tasks for this Notion task (use cached data)
        matching_tasks = await find_tasks_by_notion_id(todoist, cached_todoist_tasks, notion_id, task_notion_map)
        
        if not matching_tasks:
            # If the Notion task is completed and we don't find any matching Todoist tasks,
            # do nothing - the task might already be completed in Todoist (and thus not returned by get_tasks())
            if is_completed:
                print(f"Notion task {notion_id} is completed but no matching Todoist task found - doing nothing")
                return 1
            
            # Create new task only if the Notion task is not completed
            try:
                create_fields = todoist_fields.copy()
                if parent_task_id:
                    create_fields["parent_id"] = parent_task_id
                if project_id:
                    create_fields["project_id"] = project_id
                
                # Ensure From Notion label is added
                if "labels" not in create_fields:
                    create_fields["labels"] = []
                if from_notion_label and from_notion_label not in create_fields["labels"]:
                    create_fields["labels"].append(from_notion_label)
                
                task = await todoist.add_task(**create_fields)
                await todoist.add_comment(task_id=task.id, content=f"Notion ID: {notion_id}")
                print(f"Created new task {task.id} from Notion task {notion_id}")
                return 1
            except Exception as e:
                print(f"Failed to create task from Notion {notion_id}: {e}")
                return 0
        else:
            # Update existing task
            first_task = matching_tasks[0]
            try:
                update_fields = {}
                
                # Handle completion status first
                if is_completed and not first_task.is_completed:
                    await todoist.close_task(task_id=first_task.id)
                    print(f"Marked task {first_task.id} as completed")
                    return 1
                elif not is_completed and first_task.is_completed:
                    await todoist.reopen_task(task_id=first_task.id)
                    print(f"Marked task {first_task.id} as not completed")
                    return 1
                elif is_completed and first_task.is_completed:
                    return 1  # Already in desired state
                
                # Handle due dates
                if "due_string" in todoist_fields:
                    update_fields["due_string"] = todoist_fields["due_string"]
                elif "due_date" in todoist_fields:
                    due_str = todoist_fields["due_date"]
                    if "T" in due_str:  # ISO format with time
                        due_str = due_str.split("T")[0]  # Keep only the date part
                    update_fields["due_date"] = due_str
                
                # Handle other fields
                for field in ["content", "description", "priority"]:
                    if field in todoist_fields:
                        update_fields[field] = todoist_fields[field]
                
                # Handle project update
                if project_id is not None and project_id != first_task.project_id:
                    update_fields["project_id"] = project_id
                    print(f"Updating task {first_task.id} project to: {project_id}")
                
                # Handle labels - ensure From Notion label is present
                current_labels = getattr(first_task, 'labels', []) or []
                if "labels" in todoist_fields:
                    labels = todoist_fields["labels"]
                else:
                    labels = current_labels.copy()
                
                if from_notion_label and from_notion_label not in labels:
                    labels.append(from_notion_label)
                update_fields["labels"] = labels
                
                # Update the task if there are any changes
                if update_fields:
                    try:
                        await todoist.update_task(task_id=first_task.id, **update_fields)
                        print(f"Updated task {first_task.id} from Notion task {notion_id}")
                    except Exception as e:
                        print(f"Failed to update task {first_task.id}: {e}")
                        return 0
                
                # Handle parent task relationship after other updates
                if parent_task_id and parent_task_id != first_task.parent_id:
                    try:
                        await todoist.update_task(task_id=first_task.id, parent_id=parent_task_id)
                        print(f"Updated parent relationship for task {first_task.id} to {parent_task_id}")
                    except Exception as e:
                        print(f"Failed to update parent relationship for {first_task.id}: {e}")
                
                return 1
            except Exception as e:
                print(f"Failed to process task {first_task.id}: {e}")
                return 0
    except Exception as e:
        print(f"Failed to process Notion task {notion_id}: {e}")
        return 0

async def count_non_completed_child_tasks(notion, parent_page_id, config):
    """Count non-completed child tasks for a given parent in Notion"""
    try:
        # Get the parent field name from config
        parent_field = config.get("parent_task_field", {}).get("name")
        if not parent_field:
            return 0

        # Get completion field info from config
        completion_field = config.get("completion_field", {})
        if not completion_field:
            return 0
        
        field_name = completion_field["name"]
        done_value = completion_field["done_value"]

        # Query for child tasks
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "and": [
                    {
                        "property": parent_field,
                        "relation": {
                            "contains": parent_page_id
                        }
                    },
                    {
                        "property": field_name,
                        "status": {
                            "does_not_equal": done_value
                        }
                    }
                ]
            }
        )
        
        count = len(response["results"])
        print(f"Found {count} non-completed child tasks for parent {parent_page_id}")
        return count
    except Exception as e:
        print(f"Error counting child tasks: {e}")
        return 0

if __name__ == "__main__":
    asyncio.run(sync()) 