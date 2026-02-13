"""Notion webhook receiver for Notion-Todoist sync"""
import os
import hmac
import hashlib
from typing import Callable, Optional, Dict, Any
from datetime import datetime

import asyncio
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel

from notion_todoist_sync.sync.bidirectional_sync import BidirectionalSyncEngine

app = FastAPI(title="Notion Webhook Receiver")


class NotionWebhookEvent(BaseModel):
    """Model for Notion webhook events"""
    type: str
    id: str
    timestamp: Optional[str] = None
    entity: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None


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
        "service": "notion-webhook",
        "timestamp": datetime.utcnow().isoformat(),
        "last_event": get_last_webhook_event(),
        "sync_engine_configured": _sync_engine is not None,
    }


@app.get("/webhooks/notion")
async def notion_webhook_challenge(request: Request):
    """
    Handle Notion webhook challenge for verification.
    Notion sends a GET request with a 'challenge' query parameter
    to verify the webhook endpoint.
    """
    challenge = request.query_params.get("challenge")
    if not challenge:
        raise HTTPException(status_code=400, detail="Missing challenge parameter")

    return {"challenge": challenge}


@app.post("/webhooks/notion")
async def receive_notion_webhook(
    request: Request,
    x_notion_signature: Optional[str] = Header(None),
):
    """
    Receive webhook events from Notion.

    Notion sends webhook events when pages or databases are updated.
    """

    try:
        # Get raw body for signature verification
        body = await request.body()

        # Verify signature if secret is configured
        secret = os.getenv("NOTION_WEBHOOK_SECRET")
        if secret and x_notion_signature:
            expected_signature = hmac.new(
                secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(x_notion_signature, expected_signature):
                raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse JSON body
        event_data = await request.json()

        # Validate event structure
        if "type" not in event_data or "id" not in event_data:
            raise HTTPException(status_code=400, detail="Invalid event structure")

        event = NotionWebhookEvent(**event_data)

        # Store event info
        event_info = {
            "type": event.type,
            "id": event.id,
            "timestamp": event.timestamp,
            "data": event.data,
        }
        set_last_webhook_event(event_info)

        # Process event (lightweight: just extracts page_id and queues to orchestrator)
        await process_notion_event(event)

        return {"status": "accepted", "type": event.type}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error processing Notion webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def process_notion_event(event: NotionWebhookEvent):
    """Process a Notion webhook event"""
    try:
        event_type = event.type

        print(f"Processing Notion event: {event_type}")

        # Only process relevant events
        relevant_events = [
            "page.properties_updated",
            "page.content_updated",
            "page.created",
            "page.deleted",
        ]

        if event_type not in relevant_events:
            print(f"Ignoring event type: {event_type}")
            return

        # Extract page ID from entity (Notion API v2025-09-03 format)
        page_id = None
        if event.entity and "id" in event.entity:
            page_id = event.entity["id"]
        elif event.data and "id" in event.data:
            page_id = event.data["id"]

        if not page_id:
            print(f"No page ID found in event data")
            return

        # Queue event to orchestrator via callback (orchestrator handles the actual sync)
        if _event_callback:
            _event_callback("notion", event_type, {"page_id": page_id})
        else:
            print("Warning: Event callback not configured")

    except Exception as e:
        print(f"Error processing Notion event: {e}")
