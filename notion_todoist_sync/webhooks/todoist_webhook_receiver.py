"""Todoist webhook receiver for Notion-Todoist sync"""
import os
import hmac
import hashlib
from typing import Callable, Optional
from datetime import datetime

import asyncio
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel

from notion_todoist_sync.sync.bidirectional_sync import BidirectionalSyncEngine

app = FastAPI(title="Todoist Webhook Receiver")


class TodoistWebhookEvent(BaseModel):
    """Model for Todoist webhook events"""
    event_name: str
    event_data: dict
    user_id: str


# Global references (will be set by the orchestrator)
_sync_engine: Optional[BidirectionalSyncEngine] = None
_event_callback: Optional[Callable] = None


def set_sync_engine(engine: BidirectionalSyncEngine):
    """Set the sync engine for the webhook receiver"""
    global _sync_engine
    _sync_engine = engine


def set_event_callback(callback: Callable):
    """Set a callback function to handle webhook events"""
    global _event_callback
    _event_callback = callback


def get_last_webhook_event() -> dict:
    """Get information about the last webhook event"""
    global _last_webhook_event
    return getattr(app, "last_webhook_event", {})


def set_last_webhook_event(event: dict):
    """Store information about the last webhook event"""
    app.last_webhook_event = event


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "todoist-webhook",
        "timestamp": datetime.utcnow().isoformat(),
        "last_event": get_last_webhook_event(),
        "sync_engine_configured": _sync_engine is not None,
    }


@app.post("/webhooks/todoist")
async def receive_todoist_webhook(
    request: Request,
    x_todoist_signature: Optional[str] = Header(None),
):
    """
    Receive webhook events from Todoist.

    Todoist sends webhook events when tasks are added, updated, completed, etc.
    """
    try:
        # Get raw body for signature verification
        body = await request.body()

        # Verify signature if secret is configured
        secret = os.getenv("TODOIST_WEBHOOK_SECRET")
        if secret and x_todoist_signature:
            expected_signature = hmac.new(
                secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(x_todoist_signature, expected_signature):
                raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse JSON body
        event_data = await request.json()

        # Validate event structure
        if "event_name" not in event_data or "event_data" not in event_data:
            raise HTTPException(status_code=400, detail="Invalid event structure")

        event = TodoistWebhookEvent(**event_data)

        # Store event info
        event_info = {
            "event_name": event.event_name,
            "event_data": event.event_data,
            "timestamp": datetime.utcnow().isoformat(),
        }
        set_last_webhook_event(event_info)

        # Process event (lightweight: just extracts task_id and queues to orchestrator)
        await process_todoist_event(event)

        return {"status": "accepted", "event": event.event_name}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error processing Todoist webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def process_todoist_event(event: TodoistWebhookEvent):
    """Process a Todoist webhook event"""
    try:
        event_name = event.event_name
        event_data = event.event_data

        print(f"Processing Todoist event: {event_name}")

        # Extract task ID
        task_id = None
        if "id" in event_data:
            task_id = event_data["id"]
        elif "task" in event_data:
            task_id = event_data["task"]["id"]

        if not task_id:
            print(f"No task ID found in event data")
            return

        # Only process relevant events
        relevant_events = [
            "item:added",
            "item:updated",
            "item:completed",
            "item:uncompleted",
            "item:deleted",
        ]

        if event_name not in relevant_events:
            print(f"Ignoring event type: {event_name}")
            return

        # Queue event to orchestrator via callback (orchestrator handles the actual sync)
        if _event_callback:
            _event_callback("todoist", event_name, {"task_id": task_id})
        else:
            print("Warning: Event callback not configured")

    except Exception as e:
        print(f"Error processing Todoist event: {e}")
