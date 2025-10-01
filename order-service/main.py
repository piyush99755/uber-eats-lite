from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import orders
from schemas import Order, OrderCreate
from database import database, metadata, engine

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
    query = orders.insert().values(id=order_id, user_id=order.user_id, items=order.items, status="pending")
    await database.execute(query)
    return Order(id=order_id, **order.dict(), status="pending")

@app.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    query = orders.select().where(orders.c.id == order_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**record)

@app.get("/health")
def health():
    return {"status": "order-service healthy"}
