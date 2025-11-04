import asyncio
import uuid
import os
from typing import Optional
from fastapi import FastAPI, Query
from database import database, metadata, engine
from models import notifications, events
from schemas import NotificationCreate, Notification
from consumer import poll_sqs
from events import publish_event

app = FastAPI(title="Notification Service")

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
_sqs_task: asyncio.Task | None = None  # Keep track of SQS polling task


# ---------------------------------------------------------------------
# Startup / Shutdown Lifecycle
# ---------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    """Initialize database and start background tasks."""
    await database.connect()
    metadata.create_all(engine)

    global _sqs_task
    if USE_AWS and (_sqs_task is None or _sqs_task.done()):
        _sqs_task = asyncio.create_task(poll_sqs())
        print("[Notification Service] AWS mode — SQS polling started.")
    else:
        print("[Notification Service] Local mode — no SQS polling.")


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown for DB and background tasks."""
    if USE_AWS and _sqs_task and not _sqs_task.done():
        _sqs_task.cancel()
        try:
            await _sqs_task
        except asyncio.CancelledError:
            print("[Notification Service] SQS polling task cancelled.")

    await database.disconnect()
    print("[Notification Service] Shutdown complete.")


# ---------------------------------------------------------------------
# Notification Endpoints
# ---------------------------------------------------------------------
@app.post("/notifications", response_model=Notification)
async def create_notification_api(notification: NotificationCreate):
    """Manually create a notification (for testing)."""
    notification_id = str(uuid.uuid4())

    query = notifications.insert().values(
        id=notification_id,
        user_id=notification.user_id,
        title=notification.title,
        message=notification.message
    )
    await database.execute(query)

    # Publish event to event bus + store in DB
    await publish_event(
        "notification.created",
        {
            "id": notification_id,
            "user_id": notification.user_id,
            "title": notification.title,
            "message": notification.message
        }
    )

    return Notification(id=notification_id, **notification.dict())


@app.get("/notifications", response_model=list[Notification])
async def list_notifications():
    """List all stored notifications."""
    rows = await database.fetch_all(
        notifications.select().order_by(notifications.c.id.desc())
    )
    return [Notification(**dict(r)) for r in rows]


@app.get("/notifications/health")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "notification-service"}


# ---------------------------------------------------------------------
# Event Dashboard Endpoint
# ---------------------------------------------------------------------
@app.get("/notifications/events")
async def list_events(
    limit: int = Query(50, gt=0, le=200),
    event_type: Optional[str] = None,
    source_service: Optional[str] = None,
):
    """
    Returns recent system events (for Event Dashboard).
    Optionally filter by event type or source service.
    """
    query = events.select()
    if event_type:
        query = query.where(events.c.event_type == event_type)
    if source_service:
        query = query.where(events.c.source_service == source_service)
    query = query.order_by(events.c.occurred_at.desc()).limit(limit)

    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]
