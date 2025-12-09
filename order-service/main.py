# main.py
import uuid
import asyncio
import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Any

import jwt
from fastapi import FastAPI, HTTPException, Request, Depends, WebSocket, WebSocketDisconnect, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from database import database
from models import orders, event_logs
from schemas import OrderCreate, Order, EventLog, OrderUpdate
from events import publish_event, publish_order_created_event
from consumer import poll_queue, handle_payment_completed, handle_driver_assigned, handle_driver_failed, handle_driver_pending
from shared.auth import get_optional_user
from sse_clients import clients

load_dotenv()

# ------------------------- CONFIG -------------------------
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

# ------------------------- AUTH HELPERS -------------------------
def validate_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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

# ------------------------- HELPERS -------------------------
def format_order(row: Dict[str, Any]) -> Order:
    """Ensure driver_name and items are always set."""
    data = dict(row)
    if data.get("driver_name") is None:
        data["driver_name"] = "Unassigned"
    if isinstance(data.get("items"), str):
        try:
            data["items"] = json.loads(data["items"])
        except Exception:
            data["items"] = []
    return Order(**data)

# ------------------------- STARTUP / SHUTDOWN -------------------------
@app.on_event("startup")
async def startup():
    logger.info("Connecting database...")
    await database.connect()

    PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
    DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
    ORDER_DELIVERED_QUEUE_URL = os.getenv("ORDER_DELIVERED_QUEUE_URL")

    # Start SQS pollers
    asyncio.create_task(poll_queue(PAYMENT_QUEUE_URL, {"payment.completed": handle_payment_completed}, "payment.queue"))
    logger.info("🚀 Started SQS payment queue consumer")

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

# ------------------------- ORDERS CRUD -------------------------
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate, user=Depends(get_current_user), request: Request = None):
    trace_id = request.state.trace_id
    order_id = str(uuid.uuid4())
    user_name = request.headers.get("x-user-name") or "You"

    await database.execute(
        orders.insert().values(
            id=order_id,
            user_id=order.user_id,
            user_name=user_name,
            items=json.dumps(order.items),
            total=order.total,
            status="pending",
            payment_status="pending",
            driver_id=None,
            driver_name=None,
            delivered_at=None,
        )
    )

    order_data = {
        "id": order_id,
        "user_id": order.user_id,
        "user_name": user_name,
        "items": order.items,
        "total": order.total,
        "status": "pending",
        "payment_status": "pending",
        "driver_id": None,
        "driver_name": "Unassigned"
    }

    await publish_order_created_event(order_data, trace_id=trace_id)
    logger.info(f"[TRACE {trace_id}] ✅ Order {order_id} created by {user['id']}")
    return Order(**order_data)

@app.get("/orders", response_model=List[Order])
async def list_orders(user=Depends(get_current_user)):
    rows = await database.fetch_all(orders.select())
    return [format_order(row) for row in rows]

@app.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str, user=Depends(get_current_user)):
    row = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return format_order(row)

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
    if body.driver_name is not None:
        update_vals["driver_name"] = body.driver_name
    if body.payment_status is not None:
        update_vals["payment_status"] = body.payment_status

    await database.execute(orders.update().where(orders.c.id == order_id).values(**update_vals))
    updated = {**dict(existing), **update_vals}
    return format_order(updated)

@app.delete("/orders/{order_id}")
async def delete_order(order_id: str, user=Depends(get_current_user), request: Request = None):
    trace_id = request.state.trace_id
    existing = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    if user["role"] != "admin" and existing["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden: not owner or admin")
    await database.execute(orders.delete().where(orders.c.id == order_id))
    await publish_event("order.deleted", {"id": order_id}, trace_id=trace_id)
    logger.info(f"[TRACE {trace_id}] 🗑️ Order {order_id} deleted by {user['id']}")
    return {"message": "Order deleted"}

# ------------------------- DELIVER ORDER -------------------------
@app.post("/orders/{order_id}/deliver", response_model=Order)
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
        return format_order(order)

    await database.execute(
        orders.update().where(orders.c.id == order_id).values(
            status="delivered",
            updated_at=datetime.utcnow()
        )
    )

    updated_order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    await publish_event(
        "order.delivered",
        {
            "id": f"order.delivered_{order_id}_{datetime.utcnow().timestamp()}",
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": updated_order.get("driver_name") or "Unassigned",
            "items": json.loads(updated_order.get("items", "[]")),
            "total": updated_order.get("total"),
            "delivered_at": datetime.utcnow().isoformat()
        },
        trace_id=user.get("trace_id")
    )
    return format_order(updated_order)

# ------------------------- ASSIGN DRIVER -------------------------
@app.put("/orders/{order_id}/assign-driver", response_model=Order)
async def assign_driver_to_order(
    order_id: str,
    payload: dict = Body(...),
    user=Depends(get_current_user),
    request: Request = None
):
    trace_id = request.state.trace_id if request else str(uuid.uuid4())

    order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Extract driver info with fallback
    driver_id = payload.get("driver_id")
    driver_name = payload.get("driver_name") or "Assigned"  # fallback if driver_name missing
    status = payload.get("status", "assigned")

    if not driver_id:
        raise HTTPException(status_code=400, detail="driver_id is required")

    # Update order in DB
    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(driver_id=driver_id, driver_name=driver_name, status=status)
    )

    # Fetch updated order
    updated_order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    updated_data = dict(updated_order)

    # Parse items JSON
    try:
        updated_data["items"] = json.loads(updated_data.get("items", "[]"))
    except Exception:
        updated_data["items"] = []

    # Publish events
    await publish_event(
        "driver.assigned",
        {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "user_id": updated_data.get("user_id"),
            "user_name": updated_data.get("user_name"),
            "items": updated_data.get("items"),
            "total": updated_data.get("total"),
            "status": status
        },
        trace_id=trace_id
    )

    await publish_event(
        "order.updated",
        {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "status": status
        },
        trace_id=trace_id
    )

    logger.info(f"[TRACE {trace_id}] ✏️ Driver {driver_name} assigned to order {order_id}")
    return Order(**updated_data)
