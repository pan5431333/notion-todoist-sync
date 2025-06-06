# Notion-Todoist Sync

A Python script that synchronizes tasks between Notion and Todoist, with support for:
- Parent-child task relationships
- Custom field mappings
- Rich text descriptions
- Project synchronization
- Priority mapping
- Due date handling

## Features

- **Notion to Todoist Sync**: Keeps tasks in sync between Notion and Todoist
- **Smart Field Mapping**: Configurable mapping between Notion and Todoist fields
- **Parent-Child Tasks**: Creates parent-child relationships in Todoist based on Notion relations
- **Rich Descriptions**: Combines multiple Notion fields into formatted Todoist descriptions
- **Duplicate Prevention**: Prevents duplicate tasks by tracking Notion IDs
- **Async Support**: Uses async/await for better performance
- **Scheduled Sync**: Configurable scheduling with cron support

## Prerequisites

- Python 3.7 or higher
- macOS, Linux, or WSL (Windows Subsystem for Linux)
- Access to Notion API (with integration token)
- Access to Todoist API (with API token)

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/notion-todoist-sync.git
   cd notion-todoist-sync
   ```

2. Install and set up the project:
   ```bash
   make install  # Install Poetry and dependencies
   make setup    # Create config files
   ```

3. Update the configuration files:
   - `.env`: Add your API tokens
   - `config/sync_config.json`: Configure field mappings
   - `config/schedule_config.json`: Configure sync schedule

4. Run the sync:
   ```bash
   make run  # Run once
   # or
   make schedule  # Set up scheduled sync
   ```

5. Monitor the sync:
   ```bash
   make logs    # View live logs
   make status  # Check sync status
   ```

## Make Commands Reference

### Setup and Installation
```bash
make install   # Install Poetry and project dependencies
make setup     # Set up config files with defaults
make update    # Update dependencies to latest versions
```

### Running and Scheduling
```bash
make run       # Run sync once
make schedule  # Set up scheduled sync
make stop      # Stop scheduled sync
```

### Monitoring and Maintenance
```bash
make logs      # View sync logs in real-time
make status    # Check sync and cron job status
make clean     # Clean up generated files
```

### Development
```bash
make shell     # Spawn a shell in the virtual environment
make check     # Run code quality checks (black, flake8, mypy)
```

### Help
```bash
make help      # Show all available commands with descriptions
```

## Configuration Guide

### Environment Variables (`.env`)
```bash
NOTION_TOKEN=your_notion_token           # From Notion integrations page
NOTION_DATABASE_ID=your_database_id      # From your Notion database URL
TODOIST_TOKEN=your_todoist_token        # From Todoist integrations settings
```

### Field Mapping (`config/sync_config.json`)
```json
{
  "field_mapping": {
    "任务名称": "content",        // Task title
    "计划时间": "due_date",      // Due date
    "优先级": "priority",        // Priority (1-4)
    "项目": "project",          // Project name
    "标签": "labels"           // Task labels
  },
  "parent_task_field": {
    "name": "关联循证记录",      // Relation field for parent tasks
    "create_parent": true,
    "title_field": "Hypothesis" // Field to use as parent task title
  },
  "description_fields": {
    "enabled": true,
    "fields": [
      {
        "name": "启动动作",
        "label": "启动动作",
        "format": "### 启动动作\n{value}"
      }
    ],
    "separator": "\n\n"
  }
}
```

### Schedule Configuration (`config/schedule_config.json`)
```json
{
    "schedule": {
        "enabled": true,
        "interval_minutes": 1,
        "time_window": {
            "enabled": false,
            "start_time": "09:00",
            "end_time": "17:00"
        },
        "log_file": "sync.log"
    }
}
```

The schedule configuration allows you to:
- Enable/disable scheduled syncing (`enabled`)
- Set the sync interval in minutes (`interval_minutes`)
- Optionally restrict syncing to a specific time window:
  - Enable time window with `time_window.enabled`
  - Set working hours with `start_time` and `end_time` (24-hour format)
- Specify the log file location (`log_file`)

For example:
- To sync every 5 minutes: set `interval_minutes` to 5
- To sync every hour during work hours: set `interval_minutes` to 60 and enable the time window
- To disable scheduled syncing: set `enabled` to false

Use `make schedule` to apply the schedule configuration and `make unschedule` to remove it.

## Troubleshooting

### Common Issues

1. **Sync not running on schedule**
   ```bash
   make status  # Check if cron job is active
   make logs    # Check for errors in logs
   ```

2. **Missing dependencies**
   ```bash
   make install  # Reinstall dependencies
   ```

3. **Configuration errors**
   ```bash
   make setup    # Reset config files to defaults
   ```

### Logs and Debugging

- View live logs: `make logs`
- Check sync status: `make status`
- Clean and restart: 
  ```bash
  make stop     # Stop sync
  make clean    # Clean up
  make install  # Reinstall
  make schedule # Restart sync
  ```

## Development

### Setting Up Development Environment

1. Install dependencies and setup:
   ```bash
   make install
   make setup
   ```

2. Start development shell:
   ```bash
   make shell
   ```

3. Run code quality checks:
   ```bash
   make check
   ```

### Project Structure

```
notion-todoist-sync/
├── notion_todoist_sync/     # Main package directory
│   ├── __init__.py
│   ├── run_sync.py         # Entry point script
│   ├── sync_notion_to_todoist.py  # Main sync logic
│   └── todoist_async_wrapper.py   # Todoist API wrapper
├── config/                  # Configuration directory
│   ├── sync_config.json    # Field mapping config
│   └── schedule_config.json # Schedule config
├── run_sync.sh             # Shell script for cron job
├── Makefile               # Project automation
├── pyproject.toml         # Poetry project file
└── README.md             # This file
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create your feature branch
3. Run checks before committing:
   ```bash
   make check
   ```
4. Submit a pull request

## Support

- Check `make help` for available commands
- View logs with `make logs`
- Check status with `make status`
- Report issues on GitHub 