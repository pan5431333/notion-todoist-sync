"""
Main entry point for Notion-Todoist synchronization

Supports both legacy sync (from sync_notion_to_todoist.py) and
new orchestrator-based sync.
"""
import os
import sys
from dotenv import load_dotenv
import asyncio

from notion_todoist_sync.sync.orchestrator import SyncOrchestrator
from notion_todoist_sync.sync_notion_to_todoist import sync as legacy_sync


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

    # Check if using orchestrator (new) or legacy sync
    use_orchestrator = os.getenv("USE_ORCHESTRATOR", "false").lower() == "true"

    try:
        if use_orchestrator:
            print("Using new orchestrator-based sync")
            asyncio.run(run_orchestrator_sync())
        else:
            print("Using legacy sync")
            asyncio.run(legacy_sync())
    except Exception as e:
        print(f"Error running sync: {e}")
        raise


async def run_orchestrator_sync():
    """Run sync using the new orchestrator"""
    orchestrator = SyncOrchestrator()
    await orchestrator.initialize()
    await orchestrator.run_full_sync()
    print("Sync completed")


if __name__ == "__main__":
    main() 