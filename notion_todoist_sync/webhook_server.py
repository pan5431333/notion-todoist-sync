"""Webhook server entry point for Notion-Todoist sync"""
import os
import signal
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from notion_todoist_sync.sync.orchestrator import SyncOrchestrator
from notion_todoist_sync.webhooks.todoist_webhook_receiver import app as todoist_webhook_app
from notion_todoist_sync.webhooks.notion_webhook_receiver import app as notion_webhook_app


# Global orchestrator instance
_orchestrator: SyncOrchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the orchestrator lifecycle"""
    global _orchestrator

    # Startup
    print("Starting webhook server...")
    _orchestrator = SyncOrchestrator()
    await _orchestrator.start()
    print("Webhook server started")

    yield

    # Shutdown
    print("Shutting down webhook server...")
    if _orchestrator:
        await _orchestrator.stop()
    print("Webhook server stopped")


# Create the main FastAPI app
app = FastAPI(
    title="Notion-Todoist Sync Webhook Server",
    description="Real-time bidirectional sync between Notion and Todoist",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount the webhook apps
app.mount("/todoist", todoist_webhook_app)
app.mount("/notion", notion_webhook_app)


# Handle Notion webhook verification at top-level /webhooks/notion
@app.get("/webhooks/notion")
async def notion_webhook_challenge(challenge: str = Query(...)):
    """Handle Notion webhook verification challenge at /webhooks/notion"""
    return {"challenge": challenge}


# Handle Notion webhook events at top-level /webhooks/notion
@app.post("/webhooks/notion")
async def notion_webhook_events(request: Request):
    """Handle Notion webhook events at /webhooks/notion"""
    # Get the raw body and process the event
    body = await request.body()

    # Parse JSON
    import json
    event_data = json.loads(body.decode())

    # Handle verification token (used during Notion webhook setup)
    if "verification_token" in event_data:
        print(f"VERIFICATION TOKEN: {event_data['verification_token']}", flush=True)
        return {"status": "accepted"}

    # Validate event structure
    if "type" not in event_data or "id" not in event_data:
        return {"status": "error", "detail": "Invalid event structure"}

    # Extract page ID from entity (Notion API v2025-09-03 format)
    entity = event_data.get("entity", {})
    page_id = entity.get("id")

    # Queue event to orchestrator with extracted page_id
    if _orchestrator and page_id:
        _orchestrator.queue_sync_event("notion", event_data.get("type"), {"page_id": page_id})

    return {"status": "accepted", "type": event_data.get("type")}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Notion-Todoist Sync Webhook Server",
        "status": "running",
        "endpoints": {
            "todoist_webhook": "/todoist/webhooks/todoist",
            "notion_webhook": "/notion/webhooks/notion",
            "health": "/health",
            "status": "/status",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    global _orchestrator
    if _orchestrator:
        return {
            "status": "healthy",
            "orchestrator_running": _orchestrator._is_running,
        }
    return {
        "status": "starting",
        "orchestrator_running": False,
    }


@app.get("/status")
async def status():
    """Detailed status endpoint"""
    global _orchestrator
    if _orchestrator:
        return _orchestrator.get_status()
    return {"error": "Orchestrator not initialized"}


def main():
    """Main entry point for the webhook server"""
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")

    print(f"Starting webhook server on {host}:{port}")

    # Set up signal handlers for graceful shutdown
    def handle_shutdown(signum, frame):
        print(f"Received signal {signum}, shutting down...")
        # Uvicorn will handle graceful shutdown

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
