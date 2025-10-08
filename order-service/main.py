import uuid
from fastapi import FastAPI, HTTPException
from database import database
from models import orders
from schemas import OrderCreate, Order, AssignDriver
from events import publish_event

app = FastAPI()

# ------------------------
# Startup & shutdown events
# ------------------------
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

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
        driver_id=None  # ensure column exists
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
# Assign Driver endpoint
# ------------------------
@app.post("/orders/{order_id}/assign-driver")
async def assign_driver(order_id: str, assignment: AssignDriver):
    # 1. Check if order exists
    query = orders.select().where(orders.c.id == order_id)
    existing_order = await database.fetch_one(query)
    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Update order with driver_id
    update_query = orders.update().where(orders.c.id == order_id).values(driver_id=assignment.driver_id)
    await database.execute(update_query)

    # 3. Publish DriverAssigned event
    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": assignment.driver_id,
        "user_id": existing_order["user_id"]
    })

    return {"message": f"Driver {assignment.driver_id} assigned to order {order_id}"}
