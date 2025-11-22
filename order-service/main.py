# main.py
import uuid
import asyncio
import json
import os
import logging
import jwt  # PyJWT
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from database import database
from models import orders, event_logs
from schemas import OrderCreate, Order, EventLog, OrderUpdate
from events import publish_event
# import handlers & poll_queue from consumer (no circular import)
from consumer import (
    poll_queue,
    handle_payment_completed,
    handle_driver_assigned,
    handle_driver_failed,
    handle_driver_pending
)
from ws_manager import manager  # WebSocket manager
from shared.auth import get_optional_user
from sse_clients import clients
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
SECRET_KEY = os.getenv("JWT_SECRET", "demo_secret")
ALGORITHM = "HS256"

logger = logging.getLogger("order-service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)

app = FastAPI(title="Order Service", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ----------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------
def validate_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None

def get_current_user(request: Request):
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    return {"id": user_id, "role": role, "trace_id": trace_id}

def admin_required(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

# ----------------------------------------------------------------------
# Startup / Shutdown
# ----------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    logger.info("Connecting database...")
    await database.connect()

    # load envs (again) and queue urls
    PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
    DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
    ORDER_DELIVERED_QUEUE_URL = os.getenv("ORDER_DELIVERED_QUEUE_URL")

    # Start pollers using consumer.poll_queue (non-blocking background tasks)
    # Payment queue: only handle payment.completed
    asyncio.create_task(
        poll_queue(
            PAYMENT_QUEUE_URL,
            {"payment.completed": handle_payment_completed},
            "payment.queue"
        )
    )
    logger.info("🚀 Started SQS payment queue consumer")

    # Driver queue: driver events handled here
    asyncio.create_task(
        poll_queue(
            DRIVER_QUEUE_URL,
            {
                "driver.assigned": handle_driver_assigned,
                "driver_assigned": handle_driver_assigned,
                "driver.pending": handle_driver_pending,
                "driver.failed": handle_driver_failed,
                "order.delivered": lambda payload, eid=None: logger.info(f"[DriverQueue] order.delivered event received: {payload}")
            },
            "driver.queue"
        )
    )
    logger.info("🚀 Started SQS driver queue consumer")

    # Optional order-delivered queue
    if ORDER_DELIVERED_QUEUE_URL:
        asyncio.create_task(
            poll_queue(
                ORDER_DELIVERED_QUEUE_URL,
                {"order.delivered": lambda payload, eid=None: logger.info(f"[OrderDeliveredQueue] event received: {payload}")},
                "order.delivered.queue"
            )
        )

    logger.info("Startup complete.")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Disconnecting database...")
    await database.disconnect()

# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "order-service"}

# ----------------------------------------------------------------------
# Orders CRUD
# ----------------------------------------------------------------------
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate, user=Depends(get_current_user), request: Request = None):
    trace_id = request.state.trace_id
    order_id = str(uuid.uuid4())
    query = orders.insert().values(
        id=order_id,
        user_id=order.user_id,
        items=json.dumps(order.items),
        total=order.total,
        status="pending",
        payment_status="pending",
        driver_id=None,
    )
    await database.execute(query)
    payload = {
        "id": order_id,
        "user_id": order.user_id,
        "items": order.items,
        "total": order.total,
        "status": "pending",
        "payment_status": "pending",
    }
    await publish_event("order.created", payload, trace_id=trace_id)
    logger.info(f"[TRACE {trace_id}] ✅ Order {order_id} created by {user['id']}")
    return Order(id=order_id, status="pending", payment_status="pending", **order.dict())

@app.get("/orders", response_model=List[Order])
async def list_orders(user=Depends(get_current_user)):
    rows = await database.fetch_all(orders.select())
    result = []
    for row in rows:
        data = dict(row)
        try:
            data["items"] = json.loads(data["items"])
        except Exception:
            data["items"] = []
        result.append(Order(**data))
    return result

@app.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str, user=Depends(get_current_user)):
    row = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    data = dict(row)
    try:
        data["items"] = json.loads(data["items"])
    except Exception:
        pass
    return Order(**data)

@app.put("/orders/{order_id}", response_model=Order)
async def update_order(order_id: str, body: OrderUpdate, user=Depends(get_current_user), request: Request = None):
    trace_id = request.state.trace_id
    existing = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")

    update_vals: Dict[str, Any] = {}
    if body.items is not None:
        update_vals["items"] = json.dumps(body.items)
    if body.total is not None:
        update_vals["total"] = body.total
    if body.status is not None:
        update_vals["status"] = body.status
    if body.driver_id is not None:
        update_vals["driver_id"] = body.driver_id

    await database.execute(orders.update().where(orders.c.id == order_id).values(**update_vals))
    updated = {**dict(existing), **update_vals}
    try:
        updated["items"] = json.loads(updated["items"])
    except Exception:
        pass

    await publish_event("order.updated", {"id": order_id, **update_vals}, trace_id=trace_id)
    logger.info(f"[TRACE {trace_id}] ✏️ Order {order_id} updated by {user['id']}")
    return Order(**updated)

@app.delete("/orders/{order_id}")
async def delete_order(order_id: str, user=Depends(get_current_user), request: Request = None):
    trace_id = request.state.trace_id
    existing = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Only allow admin or order owner
    if user["role"] != "admin" and existing["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden: not owner or admin")
    
    await database.execute(orders.delete().where(orders.c.id == order_id))
    await publish_event("order.deleted", {"id": order_id}, trace_id=trace_id)
    logger.info(f"[TRACE {trace_id}] 🗑️ Order {order_id} deleted by {user['id']}")
    return {"message": "Order deleted"}

# ----------------------------------------------------------------------
# Event logs
# ----------------------------------------------------------------------
@app.get("/events", response_model=List[EventLog])
async def get_events(limit: int = 50, user=Depends(get_current_user)):
    rows = await database.fetch_all(event_logs.select().order_by(event_logs.c.created_at.desc()).limit(limit))
    result = []
    for row in rows:
        row = dict(row)
        if isinstance(row.get("payload"), str):
            try:
                row["payload"] = json.loads(row["payload"])
            except Exception:
                pass
        result.append(EventLog(**row))
    return result

# ----------------------------------------------------------------------
# WebSocket endpoint
# ----------------------------------------------------------------------
@app.websocket("/ws/orders")
async def websocket_orders(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# ----------------------------------------------------------------------
# SSE endpoint (ready for API Gateway proxy)
# ----------------------------------------------------------------------
@app.get("/orders/orders/events/stream")
async def sse_orders(token: str = Query(...)):
    payload = validate_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Unauthorized")

    queue = asyncio.Queue()
    clients.append(queue)

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            return
        finally:
            if queue in clients:
                clients.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/webhook/payment")
async def webhook_payment(request: Request):
    """
    Receives payment events from payment-service (local dev mode)
    """
    body = await request.json()
    payload = body.get("data", {})
    trace_id = body.get("trace_id") or "local"

    # call the shared consumer handler directly for local tests
    await handle_payment_completed(payload)

    logger.info(f"[LOCAL WEBHOOK] payment event received, trace_id={trace_id}")
    return {"status": "ok"}

@app.post("/orders/{order_id}/deliver")
async def deliver_order(order_id: str, user=Depends(get_optional_user)):
    driver_id = user.get("id")
    if not driver_id or user.get("role") != "driver":
        raise HTTPException(403, "Driver authorization required")

    order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not order:
        raise HTTPException(404, "Order not found")

    if order.get("driver_id") != driver_id:
        raise HTTPException(403, "Order not assigned to this driver")

    if order.get("status") == "delivered":
        return {"status": "already_delivered", "order_id": order_id}
    
    items = order.get("items")
    try:
        items = json.loads(items)
    except:
        pass

    await database.execute(
        orders.update().where(orders.c.id == order_id).values(
            status="delivered",
            updated_at=datetime.utcnow()
        )
    )

    event_payload = {
        "id": f"order.delivered_{order_id}_{datetime.utcnow().timestamp()}",
        "order_id": order_id,
        "driver_id": driver_id,
        "items": items,
        "total": order.get("total"),
        "delivered_at": datetime.utcnow().isoformat()
    }

    await publish_event("order.delivered", event_payload, trace_id=user.get("trace_id"))
    return {"status": "delivered", "order_id": order_id}
