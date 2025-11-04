import asyncio
import uuid
import os
from fastapi import FastAPI
from database import database, metadata, engine
from models import notifications
from schemas import NotificationCreate, Notification
from consumer import poll_sqs, publish_event

app = FastAPI(title="Notification Service")

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
_sqs_task: asyncio.Task | None = None  # Keep track of polling task


@app.on_event("startup")
async def startup():
    """Initialize the service, connect to the database and start polling if in AWS mode."""
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
    """Clean up resources and stop the polling task."""
    if USE_AWS and _sqs_task and not _sqs_task.done():
        _sqs_task.cancel()
        try:
            await _sqs_task
        except asyncio.CancelledError:
            print("[Notification Service] SQS polling task cancelled.")
    await database.disconnect()
    print("[Notification Service] Shutdown complete.")


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

    # Publish the notification creation event
    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": notification.user_id,
        "title": notification.title,
        "message": notification.message
    })

    return Notification(id=notification_id, **notification.dict())


@app.get("/notifications", response_model=list[Notification])
async def list_notifications():
    """List all stored notifications."""
    rows = await database.fetch_all(notifications.select().order_by(notifications.c.id.desc()))
    return [Notification(**dict(r)) for r in rows]


@app.get("/notifications/health")
async def health():
    return {"status": "ok", "service": "notification-service"}
