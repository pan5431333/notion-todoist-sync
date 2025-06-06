#!/usr/bin/env python3

import os
import json
import sys
from pathlib import Path
from crontab import CronTab
import shutil

def setup_cron():
    """Set up cron job based on configuration"""
    # Get absolute path to the script directory
    script_dir = Path(__file__).resolve().parent
    
    # Find poetry executable
    poetry_path = shutil.which('poetry')
    if not poetry_path:
        print("Error: Poetry not found. Please install Poetry first.")
        return
    
    # Load schedule configuration
    with open(script_dir / "schedule_config.json", 'r') as f:
        config = json.load(f)
    
    if not config["schedule"]["enabled"]:
        print("Scheduling is disabled in config")
        return
    
    interval = config["schedule"]["interval_minutes"]
    
    # Get current user's crontab
    cron = CronTab(user=True)
    
    # Remove any existing jobs for our script
    cron.remove_all(comment="notion-todoist-sync")
    
    # Create new job using poetry run
    command = f"cd {script_dir} && {poetry_path} run sync"
    job = cron.new(command=command, comment="notion-todoist-sync")
    
    # Set schedule based on interval
    if interval < 1:
        print("Interval must be at least 1 minute")
        return
    
    if interval == 1:
        job.minute.every(1)  # Every minute
    else:
        job.minute.every(interval)  # Every n minutes
    
    # Write the crontab
    cron.write()
    
    print(f"Cron job set up successfully to run every {interval} minute(s)")
    print(f"Next run will be at: {job.schedule().get_next()}")
    print(f"Command: {command}")

if __name__ == "__main__":
    setup_cron() 