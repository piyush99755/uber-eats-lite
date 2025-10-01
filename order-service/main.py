from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import orders
from schemas import OrderCreate, Order
from database import database, metadata, engine
from events import publish_event

app = FastAPI(title="Order Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/orders", response_model=Order)
async def create_order(order: OrderCreate):
    order_id = str(uuid4())
    query = orders.insert().values(id=order_id, user_id=order.user_id, total=order.total)
    await database.execute(query)
    
    await publish_event("order.created", {
        "id": order_id,
        "user_id": order.user_id,
        "total": order.total
    })
    
    return Order(id=order_id, **order.dict())

@app.get("/health")
def health():
    return {"status": "order-service healthy"}
