"""Webhook manager for registering and managing Notion and Todoist webhooks"""
import os
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime

from notion_todoist_sync.config import Configuration
from notion_todoist_sync.repositories import TodoistRepository


class WebhookManager:
    """Manages webhook registration for Notion and Todoist"""

    def __init__(self, config: Configuration, todoist_repo: TodoistRepository):
        self.config = config
        self.todoist_repo = todoist_repo

        # Track registered webhooks
        self._registered_todoist_webhooks: List[Dict[str, Any]] = []
        self._registered_notion_webhooks: List[Dict[str, Any]] = []

    async def register_all_webhooks(self) -> bool:
        """
        Register all webhooks on startup.

        Returns True if all registrations succeeded.
        """
        success = True

        # Register Todoist webhooks
        if self.config.webhook_enabled and self.config.todoist_webhook_config.get("enabled"):
            if not await self.register_todoist_webhooks():
                success = False
        else:
            print("Todoist webhooks disabled in config")

        # Register Notion webhooks
        if self.config.webhook_enabled and self.config.notion_webhook_config.get("enabled"):
            if not await self.register_notion_webhooks():
                success = False
        else:
            print("Notion webhooks disabled in config")

        return success

    async def unregister_all_webhooks(self) -> bool:
        """
        Unregister all webhooks on shutdown.

        Returns True if all unregistrations succeeded.
        """
        success = True

        # Unregister Todoist webhooks
        if not await self.unregister_todoist_webhooks():
            success = False

        # Unregister Notion webhooks
        if not await self.unregister_notion_webhooks():
            success = False

        return success

    async def register_todoist_webhooks(self) -> bool:
        """
        Register webhooks for Todoist.

        Returns True if registration succeeded.
        """
        if not self.config.webhook_url:
            print("Error: WEBHOOK_URL not configured for Todoist webhooks")
            return False

        webhook_url = f"{self.config.webhook_url}/todoist/webhooks/todoist"

        try:
            # Get current webhooks
            existing_webhooks = await self._get_todoist_webhooks()

            # Check if webhook already exists
            for webhook in existing_webhooks:
                if webhook.get("configuration", {}).get("url") == webhook_url:
                    print(f"Todoist webhook already registered: {webhook['id']}")
                    self._registered_todoist_webhooks = [webhook]
                    return True

            # Register new webhook
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.todoist.com/rest/v2/webhooks",
                    headers={
                        "Authorization": f"Bearer {self.config.todoist_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "url": webhook_url,
                        "description": "Notion-Todoist Sync",
                    },
                )
                response.raise_for_status()
                webhook_data = response.json()

            print(f"Registered Todoist webhook: {webhook_data['id']}")
            self._registered_todoist_webhooks = [webhook_data]
            return True

        except Exception as e:
            print(f"Error registering Todoist webhook: {e}")
            return False

    async def unregister_todoist_webhooks(self) -> bool:
        """
        Unregister webhooks for Todoist.

        Returns True if unregistration succeeded.
        """
        success = True

        for webhook in self._registered_todoist_webhooks:
            try:
                webhook_id = webhook.get("id")
                if not webhook_id:
                    continue

                async with httpx.AsyncClient() as client:
                    response = await client.delete(
                        f"https://api.todoist.com/rest/v2/webhooks/{webhook_id}",
                        headers={
                            "Authorization": f"Bearer {self.config.todoist_token}",
                        },
                    )
                    response.raise_for_status()

                print(f"Unregistered Todoist webhook: {webhook_id}")

            except Exception as e:
                print(f"Error unregistering Todoist webhook {webhook.get('id')}: {e}")
                success = False

        self._registered_todoist_webhooks = []
        return success

    async def register_notion_webhooks(self) -> bool:
        """
        Register webhooks for Notion.

        Returns True if registration succeeded.
        """
        if not self.config.webhook_url:
            print("Error: WEBHOOK_URL not configured for Notion webhooks")
            return False

        webhook_url = f"{self.config.webhook_url}/notion/webhooks/notion"
        database_id = self.config.notion_database_id

        try:
            # Check if webhook already exists
            existing_webhooks = await self._get_notion_webhooks()
            for webhook in existing_webhooks:
                if webhook.get("url") == webhook_url:
                    print(f"Notion webhook already registered: {webhook['id']}")
                    self._registered_notion_webhooks = [webhook]
                    return True

            # Register new webhook
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.notion.com/v1/webhooks",
                    headers={
                        "Authorization": f"Bearer {self.config.notion_token}",
                        "Content-Type": "application/json",
                        "Notion-Version": "2022-06-28",
                    },
                    json={
                        "url": webhook_url,
                        "object_type": "database",
                        "object_id": database_id,
                    },
                )
                response.raise_for_status()
                webhook_data = response.json()

            print(f"Registered Notion webhook: {webhook_data['id']}")
            self._registered_notion_webhooks = [webhook_data]
            return True

        except Exception as e:
            print(f"Error registering Notion webhook: {e}")
            return False

    async def unregister_notion_webhooks(self) -> bool:
        """
        Unregister webhooks for Notion.

        Returns True if unregistration succeeded.
        """
        success = True

        for webhook in self._registered_notion_webhooks:
            try:
                webhook_id = webhook.get("id")
                if not webhook_id:
                    continue

                async with httpx.AsyncClient() as client:
                    response = await client.delete(
                        f"https://api.notion.com/v1/webhooks/{webhook_id}",
                        headers={
                            "Authorization": f"Bearer {self.config.notion_token}",
                            "Notion-Version": "2022-06-28",
                        },
                    )
                    response.raise_for_status()

                print(f"Unregistered Notion webhook: {webhook_id}")

            except Exception as e:
                print(f"Error unregistering Notion webhook {webhook.get('id')}: {e}")
                success = False

        self._registered_notion_webhooks = []
        return success

    async def _get_todoist_webhooks(self) -> List[Dict[str, Any]]:
        """Get all Todoist webhooks"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.todoist.com/rest/v2/webhooks",
                    headers={
                        "Authorization": f"Bearer {self.config.todoist_token}",
                    },
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Error getting Todoist webhooks: {e}")
            return []

    async def _get_notion_webhooks(self) -> List[Dict[str, Any]]:
        """Get all Notion webhooks"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.notion.com/v1/webhooks",
                    headers={
                        "Authorization": f"Bearer {self.config.notion_token}",
                        "Notion-Version": "2022-06-28",
                    },
                )
                response.raise_for_status()
                return response.json().get("results", [])
        except Exception as e:
            print(f"Error getting Notion webhooks: {e}")
            return []

    def get_webhook_status(self) -> Dict[str, Any]:
        """Get current webhook status"""
        return {
            "webhook_enabled": self.config.webhook_enabled,
            "webhook_url": self.config.webhook_url,
            "todoist_webhooks": {
                "enabled": self.config.todoist_webhook_config.get("enabled"),
                "registered_count": len(self._registered_todoist_webhooks),
                "webhooks": [
                    {"id": w.get("id"), "url": w.get("configuration", {}).get("url")}
                    for w in self._registered_todoist_webhooks
                ],
            },
            "notion_webhooks": {
                "enabled": self.config.notion_webhook_config.get("enabled"),
                "registered_count": len(self._registered_notion_webhooks),
                "webhooks": [
                    {"id": w.get("id"), "url": w.get("url")}
                    for w in self._registered_notion_webhooks
                ],
            },
        }
