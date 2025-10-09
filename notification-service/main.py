import asyncio
import uuid
from fastapi import FastAPI
from database import database, metadata, engine
from models import notifications
from schemas import NotificationCreate, Notification
from events import publish_event
from consumer import poll_sqs

app = FastAPI(title="Notification Service")

# -------------------
# DB & Startup
# -------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

    # Start background consumer task
    asyncio.create_task(poll_sqs())
    print("[Notification Service] Started successfully.")


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("[Notification Service] Shutdown complete.")


# -------------------
# API Endpoints
# -------------------
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

    # Publish notification.created event
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-service"}
