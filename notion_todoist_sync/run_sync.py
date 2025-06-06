"""
Main entry point for Notion-Todoist synchronization
"""
import os
from dotenv import load_dotenv
import asyncio
from notion_todoist_sync.sync_notion_to_todoist import sync

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

    try:
        asyncio.run(sync())
    except Exception as e:
        print(f"Error running sync: {e}")
        raise

if __name__ == "__main__":
    main() 