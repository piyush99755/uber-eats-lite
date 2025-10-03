import uuid
from fastapi import FastAPI
from database import database
from models import orders
from schemas import OrderCreate, Order
from events import publish_event

app = FastAPI()

# Connect/disconnect database
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Create order endpoint
@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate):
    order_id = str(uuid.uuid4())
    query = orders.insert().values(
        id=order_id,
        user_id=order.user_id,
        items=order.items,
        total=order.total,
        status="pending"
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
