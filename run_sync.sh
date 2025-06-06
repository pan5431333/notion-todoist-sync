#!/bin/bash

# Set up logging
exec 1> >(logger -s -t $(basename $0)) 2>&1

# Load environment variables
if [ -f ~/.zshrc ]; then
    source ~/.zshrc
fi

# Set up PATH
export PATH="/Users/mengpan/.local/bin:$PATH"

# Change to the correct directory
cd /Users/mengpan/Projects/notion-todoist-sync

# Get log file path from config
LOG_FILE=$(python3 -c "import json; print(json.load(open('config/schedule_config.json'))['schedule']['log_file'])")
LOG_DIR=$(dirname "$LOG_FILE")

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Run the sync with timestamp logging
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting sync..."
if [ -n "$MAX_TASKS" ]; then
    echo "Max tasks per run: $MAX_TASKS"
    NOTION_TODOIST_MAX_TASKS=$MAX_TASKS poetry run sync >> "$LOG_FILE" 2>&1
else
    poetry run sync >> "$LOG_FILE" 2>&1
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed" 