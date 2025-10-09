import uuid
import asyncio
from fastapi import FastAPI, HTTPException
from database import database
from models import orders, event_logs
from schemas import OrderCreate, Order, AssignDriver, EventLog
from events import publish_event
from consumer import poll_messages

app = FastAPI()

# ------------------------
# Startup & shutdown events
# ------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    # Start driver.assigned consumer in background
    asyncio.create_task(poll_messages())

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ------------------------
# Health check endpoint
# ------------------------
@app.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    Used by load balancers or monitoring services.
    """
    return {"status": "ok", "service": "order-service"}


# ------------------------
# Create Order endpoint
# ------------------------
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate):
    order_id = str(uuid.uuid4())
    query = orders.insert().values(
        id=order_id,
        user_id=order.user_id,
        items=order.items,
        total=order.total,
        status="pending",
        driver_id=None
    )
    await database.execute(query)

    # Publish OrderCreated event
    await publish_event("order.created", {
        "id": order_id,
        "user_id": order.user_id,
        "items": order.items,
        "total": order.total,
        "status": "pending"
    })

    return Order(id=order_id, status="pending", **order.dict())


# ------------------------
# Get All Orders
# ------------------------
@app.get("/orders", response_model=list[Order])
async def list_orders():
    """
    Return all orders.
    """
    query = orders.select()
    results = await database.fetch_all(query)
    return [Order(**dict(result)) for result in results]


# ------------------------
# Get Order by ID
# ------------------------
@app.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    """
    Return details for a single order.
    """
    query = orders.select().where(orders.c.id == order_id)
    order = await database.fetch_one(query)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**dict(order))


# ------------------------
# Assign Driver endpoint
# ------------------------
@app.post("/orders/{order_id}/assign-driver")
async def assign_driver(order_id: str, assignment: AssignDriver):
    #  Check if order exists
    query = orders.select().where(orders.c.id == order_id)
    existing_order = await database.fetch_one(query)
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    #  Update order with driver_id
    update_query = orders.update().where(orders.c.id == order_id).values(driver_id=assignment.driver_id)
    await database.execute(update_query)

    #  Publish DriverAssigned event
    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": assignment.driver_id,
        "user_id": existing_order["user_id"]
    })

    return {"message": f"Driver {assignment.driver_id} assigned to order {order_id}"}

@app.get("/events", response_model=list[EventLog])
async def get_events(limit: int = 50):
    """
    Get recent events from event_logs table.
    Optional query parameter `limit` controls how many events to return (default 50).
    """
    import json
    from fastapi import HTTPException

    try:
        query = event_logs.select().order_by(event_logs.c.created_at.desc()).limit(limit)
        results = await database.fetch_all(query)
        
        events = []
        for row in results:
            row_dict = dict(row)
            # Parse payload if it is a string
            if isinstance(row_dict["payload"], str):
                try:
                    row_dict["payload"] = json.loads(row_dict["payload"])
                except json.JSONDecodeError:
                    # fallback: keep as string
                    pass
            events.append(EventLog(**row_dict))
        
        return events

    except Exception as e:
        print("ERROR in /events:", e)
        raise HTTPException(status_code=500, detail=str(e))

