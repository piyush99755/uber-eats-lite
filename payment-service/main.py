from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import payments
from schemas import Payment, PaymentCreate
from database import database, metadata, engine

app = FastAPI(title="Payment Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/payments", response_model=Payment)
async def create_payment(payment: PaymentCreate):
    payment_id = str(uuid4())
    query = payments.insert().values(id=payment_id, order_id=payment.order_id, amount=payment.amount, status="completed")
    await database.execute(query)
    return Payment(id=payment_id, **payment.dict(), status="completed")

@app.get("/payments/{payment_id}", response_model=Payment)
async def get_payment(payment_id: str):
    query = payments.select().where(payments.c.id == payment_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="Payment not found")
    return Payment(**record)

@app.get("/health")
def health():
    return {"status": "payment-service healthy"}

