import uuid
import asyncio
import json
from fastapi import FastAPI, HTTPException, Request, Depends
from database import database
from models import orders, event_logs
from schemas import OrderCreate, Order, AssignDriver, EventLog, OrderUpdate
from events import publish_event
from consumer import poll_messages, poll_payment_messages

app = FastAPI(title="Order Service", version="1.2.0")

# ─────────────────────────────────────────────
# 🔐 Dependencies: Current User
# ─────────────────────────────────────────────
def get_current_user(request: Request):
    """Extract user identity and tracing headers."""
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    return {"id": user_id, "role": role, "trace_id": trace_id}


def admin_required(user=Depends(get_current_user)):
    """Ensure only admins can access certain endpoints."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admins only")
    return user


# ─────────────────────────────────────────────
# 🚀 Startup & Shutdown
# ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await database.connect()
    try:
        # start driver queue consumer
        asyncio.create_task(poll_messages())
        print("[Startup] ✅ Background consumer for driver.assigned started.")

        # start payment queue consumer
        asyncio.create_task(poll_payment_messages())
        print("[Startup] ✅ Background consumer for payment.processed started.")
    except Exception as e:
        print(f"[Startup Error] ❌ Failed to start consumers: {e}")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ─────────────────────────────────────────────
# 🩺 Health Check
# ─────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "order-service"}


# ─────────────────────────────────────────────
# 🧾 Create Order
# ─────────────────────────────────────────────
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate, user=Depends(get_current_user), request: Request = None):
    order_id = str(uuid.uuid4())
    trace_id = getattr(request.state, "trace_id", user.get("trace_id"))

    # Insert order into database
    query = orders.insert().values(
        id=order_id,
        user_id=order.user_id,
        items=json.dumps(order.items),
        total=order.total,
        status="pending",
        payment_status="pending",
        driver_id=None
    )
    await database.execute(query)

    # Publish event (safe call)
    try:
        await publish_event("order.created", {
            "id": order_id,
            "user_id": order.user_id,
            "items": order.items,
            "total": order.total,
            "status": "pending",
            "payment_status": "pending"
        }, trace_id=trace_id)
    except TypeError:
        # Fallback for legacy publish_event without trace_id
        await publish_event("order.created", {
            "id": order_id,
            "user_id": order.user_id,
            "items": order.items,
            "total": order.total,
            "status": "pending",
            "payment_status": "pending"
        })

    print(f"[TRACE {trace_id}] ✅ Order {order_id} created by {user['id']}")
    return Order(id=order_id, status="pending", payment_status="pending", **order.dict())


# ─────────────────────────────────────────────
# 📋 List Orders
# ─────────────────────────────────────────────
@app.get("/orders", response_model=list[Order])
async def list_orders(user=Depends(get_current_user)):
    results = await database.fetch_all(orders.select())
    parsed = []

    for row in results:
        data = dict(row)
        try:
            data["items"] = json.loads(data["items"])
        except (TypeError, json.JSONDecodeError):
            data["items"] = []
        parsed.append(Order(**data))

    return parsed


# ─────────────────────────────────────────────
# 🔍 Get Order by ID
# ─────────────────────────────────────────────
@app.get("/orders/{order_id}", response_model=Order, tags=["Orders"])
async def get_order(order_id: str, user=Depends(get_current_user)):
    order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**dict(order))


# ─────────────────────────────────────────────
# 🚚 Assign Driver Manually
# ─────────────────────────────────────────────
@app.post("/orders/{order_id}/assign-driver", tags=["Orders"])
async def assign_driver(order_id: str, assignment: AssignDriver, user=Depends(get_current_user), request: Request = None):
    trace_id = getattr(request.state, "trace_id", user.get("trace_id"))

    existing_order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    await database.execute(
        orders.update().where(orders.c.id == order_id).values(driver_id=assignment.driver_id)
    )

    try:
        await publish_event("driver.assigned", {
            "order_id": order_id,
            "driver_id": assignment.driver_id,
            "user_id": existing_order["user_id"]
        }, trace_id=trace_id)
    except TypeError:
        await publish_event("driver.assigned", {
            "order_id": order_id,
            "driver_id": assignment.driver_id,
            "user_id": existing_order["user_id"]
        })

    print(f"[TRACE {trace_id}] 🚗 Driver {assignment.driver_id} assigned to order {order_id} by {user['id']}")
    return {"message": f"Driver {assignment.driver_id} assigned to order {order_id}"}


# ─────────────────────────────────────────────
# 📜 Events Endpoint
# ─────────────────────────────────────────────
@app.get("/events", response_model=list[EventLog], tags=["Events"])
async def get_events(limit: int = 50, user=Depends(get_current_user)):
    try:
        query = event_logs.select().order_by(event_logs.c.created_at.desc()).limit(limit)
        results = await database.fetch_all(query)

        events = []
        for row in results:
            row_dict = dict(row)
            if isinstance(row_dict["payload"], str):
                try:
                    row_dict["payload"] = json.loads(row_dict["payload"])
                except json.JSONDecodeError:
                    pass
            events.append(EventLog(**row_dict))
        return events
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# ❌ Delete Order
# ─────────────────────────────────────────────
@app.delete("/orders/{order_id}", tags=["Orders"])
async def delete_order(order_id: str, user=Depends(admin_required), request: Request = None):
    trace_id = getattr(request.state, "trace_id", user.get("trace_id"))

    existing_order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    await database.execute(orders.delete().where(orders.c.id == order_id))

    try:
        await publish_event("order.deleted", {"id": order_id}, trace_id=trace_id)
    except TypeError:
        await publish_event("order.deleted", {"id": order_id})

    print(f"[TRACE {trace_id}] 🗑️ Order {order_id} deleted by {user['id']}")
    return {"message": f"Order {order_id} deleted successfully"}


# ─────────────────────────────────────────────
# ✏️ Update Order
# ─────────────────────────────────────────────
@app.put("/orders/{order_id}", response_model=Order, tags=["Orders"])
async def update_order(order_id: str, order: OrderUpdate, user=Depends(get_current_user), request: Request = None):
    trace_id = getattr(request.state, "trace_id", user.get("trace_id"))

    existing_order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = {}
    if order.items is not None:
        update_data["items"] = json.dumps(order.items)
    if order.total is not None:
        update_data["total"] = order.total
    if order.status is not None:
        update_data["status"] = order.status
    if order.driver_id is not None:
        update_data["driver_id"] = order.driver_id

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    await database.execute(orders.update().where(orders.c.id == order_id).values(**update_data))

    updated_order = {**dict(existing_order), **update_data}
    updated_order["items"] = (
        json.loads(updated_order["items"]) if isinstance(updated_order["items"], str) else updated_order["items"]
    )

    try:
        await publish_event("order.updated", {"id": order_id, **update_data}, trace_id=trace_id)
    except TypeError:
        await publish_event("order.updated", {"id": order_id, **update_data})

    print(f"[TRACE {trace_id}] ✏️ Order {order_id} updated by {user['id']}")
    return Order(**updated_order)
