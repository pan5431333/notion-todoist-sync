# Notion-Todoist Sync

A Python script that synchronizes tasks between Notion and Todoist, with support for:
- Parent-child task relationships
- Custom field mappings
- Rich text descriptions
- Project synchronization
- Priority mapping
- Due date handling

## Features

- **Bidirectional Sync**: Keeps tasks in sync between Notion and Todoist
- **Smart Field Mapping**: Configurable mapping between Notion and Todoist fields
- **Parent-Child Tasks**: Creates parent-child relationships in Todoist based on Notion relations
- **Rich Descriptions**: Combines multiple Notion fields into formatted Todoist descriptions
- **Duplicate Prevention**: Prevents duplicate tasks by tracking Notion IDs
- **Async Support**: Uses async/await for better performance

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your API keys:
   ```
   NOTION_TOKEN=your_notion_token
   NOTION_DATABASE_ID=your_database_id
   TODOIST_TOKEN=your_todoist_token
   ```
4. Configure field mappings in `sync_config.json`:
   ```json
   {
     "field_mapping": {
       "notion_field": "todoist_field"
     },
     "parent_task_field": {
       "name": "relation_field_name",
       "create_parent": true,
       "title_field": "title_field_name"
     },
     "description_fields": {
       "enabled": true,
       "fields": [
         {
           "name": "notion_field",
           "label": "Section Label",
           "format": "### {label}\n{value}"
         }
       ],
       "separator": "\n\n"
     }
   }
   ```

## Usage

Run the sync script:
```bash
python sync_notion_to_todoist.py
```

The script will:
1. Fetch recently modified tasks from Notion
2. Create or update corresponding tasks in Todoist
3. Maintain parent-child relationships
4. Update task descriptions and other fields
5. Remove any duplicate tasks

## Requirements

- Python 3.7+
- `notion-client`
- `todoist-api-python`
- `python-dotenv`

## Configuration

### Field Mapping

Map Notion fields to Todoist fields in `sync_config.json`:
- `content`: Task title
- `due_date`: Due date
- `priority`: Task priority (1-4)
- `project`: Project name
- `labels`: Task labels

### Parent Tasks

Configure parent-child relationships:
- `name`: Notion relation field name
- `create_parent`: Whether to create parent tasks
- `title_field`: Field to use as parent task title

### Description Fields

Combine multiple Notion fields into the task description:
- `enabled`: Toggle description generation
- `fields`: List of fields to include
- `separator`: Separator between fields

## License

MIT License 