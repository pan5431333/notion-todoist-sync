#!/bin/bash

# Set up logging
exec 1> >(logger -s -t $(basename $0)) 2>&1

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load environment variables
if [ -f ~/.zshrc ]; then
    source ~/.zshrc
fi

# Add Poetry to PATH if it exists in common locations
for poetry_path in "$HOME/.local/bin" "$HOME/Library/Python/*/bin" "/usr/local/bin"; do
    if [ -f "$poetry_path/poetry" ]; then
        export PATH="$poetry_path:$PATH"
        break
    fi
done

# Change to the script directory
cd "$SCRIPT_DIR"

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