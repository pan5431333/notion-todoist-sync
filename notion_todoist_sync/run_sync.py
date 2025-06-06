"""
Main sync script for Notion-Todoist synchronization
"""
import os
import json
import asyncio
import datetime
from notion_client import Client as NotionClient
from todoist_api_python.api import TodoistAPI
from dotenv import load_dotenv
from datetime import datetime, date, timezone, timedelta

def main():
    """Main entry point for the sync script"""
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

    try:
        asyncio.run(sync())
    except Exception as e:
        print(f"Error running sync: {e}")
        raise

if __name__ == "__main__":
    main() 