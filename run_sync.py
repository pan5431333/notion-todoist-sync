#!/usr/bin/env python3

import os
import json
import sys
import logging
import asyncio
from datetime import datetime
import traceback
from pathlib import Path

# Get the directory containing this script
SCRIPT_DIR = Path(__file__).resolve().parent

def setup_logging(config):
    """Setup logging configuration"""
    log_file = config["schedule"]["log_file"]
    if not log_file.startswith('/'):
        log_file = str(SCRIPT_DIR / log_file)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def load_config(config_path):
    """Load schedule configuration"""
    if not config_path.startswith('/'):
        config_path = str(SCRIPT_DIR / config_path)
    
    with open(config_path, 'r') as f:
        return json.load(f)

def is_within_time_window(config):
    """Check if current time is within the configured time window"""
    time_window = config["schedule"]["time_window"]
    if not time_window["enabled"]:
        return True
    
    current_time = datetime.now().time()
    start_time = datetime.strptime(time_window["start_time"], "%H:%M").time()
    end_time = datetime.strptime(time_window["end_time"], "%H:%M").time()
    
    return start_time <= current_time <= end_time

async def run_sync():
    """Run the sync script"""
    try:
        # Change to the script directory
        os.chdir(SCRIPT_DIR)
        
        # Load configuration
        config = load_config('schedule_config.json')
        logger = setup_logging(config)
        
        if not config["schedule"]["enabled"]:
            logger.info("Scheduling is disabled in config")
            return
        
        if not is_within_time_window(config):
            logger.info("Current time is outside the configured time window")
            return
        
        logger.info("Starting sync process...")
        
        # Import the sync function from the main script
        from sync_notion_to_todoist import sync
        
        # Run the sync
        await sync()
        
        logger.info("Sync completed successfully")
        
    except Exception as e:
        logger.error(f"Error during sync: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Handle error notification if configured
        if config["schedule"]["error_notification"]["enabled"]:
            # You can implement email notification here
            pass

def main():
    """Synchronous entry point for the script"""
    asyncio.run(run_sync())

if __name__ == "__main__":
    main() 