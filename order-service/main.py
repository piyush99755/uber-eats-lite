import uuid
import asyncio
import json
from fastapi import FastAPI, HTTPException
from database import database
from models import orders, event_logs
from schemas import OrderCreate, Order, AssignDriver, EventLog
from events import publish_event
from consumer import poll_messages

app = FastAPI(title="Order Service")


# ------------------------
# Startup & shutdown
# ------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    try:
        asyncio.create_task(poll_messages())
        print("[Startup] Background consumer for driver.assigned started.")
    except Exception as e:
        print(f"[Startup Error] Failed to start consumer: {e}")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ------------------------
# Health
# ------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": "order-service"}


# CREATE ORDER
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate):
    order_id = str(uuid.uuid4())

    # Convert list -> JSON string for SQLite
    query = orders.insert().values(
        id=order_id,
        user_id=order.user_id,
        items=json.dumps(order.items),
        total=order.total,
        status="pending",
        driver_id=None
    )
    await database.execute(query)

    # Publish event
    await publish_event("order.created", {
        "id": order_id,
        "user_id": order.user_id,
        "items": order.items,
        "total": order.total,
        "status": "pending"
    })

    return Order(id=order_id, status="pending", **order.dict())


# LIST ORDERS
@app.get("/orders", response_model=list[Order])
async def list_orders():
    query = orders.select()
    results = await database.fetch_all(query)

    # Convert JSON string -> list
    parsed = []
    for row in results:
        data = dict(row)
        try:
            data["items"] = json.loads(data["items"])
        except (TypeError, json.JSONDecodeError):
            data["items"] = []
        parsed.append(Order(**data))

    return parsed


# ------------------------
# Get Order by ID
# ------------------------
@app.get("/orders/{order_id}", response_model=Order, tags=["Orders"])
async def get_order(order_id: str):
    query = orders.select().where(orders.c.id == order_id)
    order = await database.fetch_one(query)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**dict(order))


# ------------------------
# Assign Driver manually (optional)
# ------------------------
@app.post("/orders/{order_id}/assign-driver", tags=["Orders"])
async def assign_driver(order_id: str, assignment: AssignDriver):
    query = orders.select().where(orders.c.id == order_id)
    existing_order = await database.fetch_one(query)
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    update_query = orders.update().where(orders.c.id == order_id).values(driver_id=assignment.driver_id)
    await database.execute(update_query)

    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": assignment.driver_id,
        "user_id": existing_order["user_id"]
    })

    return {"message": f"Driver {assignment.driver_id} assigned to order {order_id}"}


# ------------------------
# Events endpoint
# ------------------------
@app.get("/events", response_model=list[EventLog], tags=["Events"])
async def get_events(limit: int = 50):
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
        print("ERROR in /events:", e)
        raise HTTPException(status_code=500, detail=str(e))

# DELETE ORDER
@app.delete("/orders/{order_id}", tags=["Orders"])
async def delete_order(order_id: str):
    query = orders.select().where(orders.c.id == order_id)
    existing_order = await database.fetch_one(query)
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    delete_query = orders.delete().where(orders.c.id == order_id)
    await database.execute(delete_query)

    await publish_event("order.deleted", {"id": order_id})
    return {"message": f"Order {order_id} deleted successfully"}
