import asyncio
import uuid
import os
from typing import Optional
from fastapi import FastAPI, Query, Request, Response, Depends, HTTPException
from database import database, metadata, engine
from models import notifications, events
from schemas import NotificationCreate, Notification
from consumer import poll_sqs
from events import publish_event
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from trace import get_or_create_trace_id

app = FastAPI(title="Notification Service")

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
_sqs_task: asyncio.Task | None = None  # Keep track of SQS polling task

# -------------------
# Prometheus metrics
# -------------------
EVENTS_PROCESSED = Counter('events_processed_total', 'Total events processed', ['event_type'])
EVENTS_FAILED = Counter('events_failed_total', 'Total events failed', ['event_type'])

@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ------------------------
# Dependencies: Current User
# ------------------------
def get_current_user(request: Request):
    """
    Extracts user info from headers: x-user-id, x-user-role, x-trace-id
    """
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    return {"id": user_id, "role": role, "trace_id": trace_id}

def admin_required(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admins only")
    return user

# -------------------
# Startup / Shutdown Lifecycle
# -------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

    global _sqs_task
    if USE_AWS and (_sqs_task is None or _sqs_task.done()):
        _sqs_task = asyncio.create_task(poll_sqs(EVENTS_PROCESSED, EVENTS_FAILED))
        print("[Notification Service] AWS mode — SQS polling started.")
    else:
        print("[Notification Service] Local mode — no SQS polling.")

@app.on_event("shutdown")
async def shutdown():
    if USE_AWS and _sqs_task and not _sqs_task.done():
        _sqs_task.cancel()
        try:
            await _sqs_task
        except asyncio.CancelledError:
            print("[Notification Service] SQS polling task cancelled.")
    await database.disconnect()
    print("[Notification Service] Shutdown complete.")

# -------------------
# Middleware: assign trace_id for HTTP requests
# -------------------
@app.middleware("http")
async def add_trace_to_request(request: Request, call_next):
    trace_id = get_or_create_trace_id(request.headers.get("X-Trace-Id"))
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response

# -------------------
# Notification Endpoints
# -------------------
@app.post("/notifications", response_model=Notification)
async def create_notification_api(
    notification: NotificationCreate, user=Depends(get_current_user)
):
    notification_id = str(uuid.uuid4())
    trace_id = user["trace_id"]

    query = notifications.insert().values(
        id=notification_id,
        user_id=notification.user_id,
        title=notification.title,
        message=notification.message
    )
    await database.execute(query)

    await publish_event(
        "notification.created",
        {
            "id": notification_id,
            "user_id": notification.user_id,
            "title": notification.title,
            "message": notification.message
        },
        trace_id=trace_id
    )

    return Notification(id=notification_id, **notification.dict())

@app.get("/notifications", response_model=list[Notification])
async def list_notifications(user=Depends(get_current_user)):
    rows = await database.fetch_all(
        notifications.select().order_by(notifications.c.id.desc())
    )
    return [Notification(**dict(r)) for r in rows]

@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-service"}

@app.get("/notifications/events")
async def list_events(
    limit: int = Query(50, gt=0, le=200),
    event_type: Optional[str] = None,
    source_service: Optional[str] = None,
    user=Depends(get_current_user)
):
    trace_id = user["trace_id"]
    query = events.select()
    if event_type:
        query = query.where(events.c.event_type == event_type)
    if source_service:
        query = query.where(events.c.source_service == source_service)
    query = query.order_by(events.c.occurred_at.desc()).limit(limit)
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]
