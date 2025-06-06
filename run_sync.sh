#!/bin/bash

# Set up logging
exec 1> >(logger -s -t $(basename $0)) 2>&1

# Load environment variables
if [ -f /root/.bashrc ]; then
    source /root/.bashrc
fi

# Set up PATH
export PATH="/root/.local/bin:$PATH"

# Change to the correct directory
cd /root/Projects/notion-todoist-sync

# Ensure log directory exists
mkdir -p logs

# Run the sync with timestamp logging
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting sync..."
/root/.local/bin/poetry run sync >> logs/sync.log 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed" 