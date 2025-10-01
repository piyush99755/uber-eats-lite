from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import payments
from schemas import PaymentCreate, Payment
from database import database, metadata, engine
from events import publish_event

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
    query = payments.insert().values(id=payment_id, order_id=payment.order_id, amount=payment.amount)
    await database.execute(query)
    
    await publish_event("payment.created", {
        "id": payment_id,
        "order_id": payment.order_id,
        "amount": payment.amount
    })
    
    return Payment(id=payment_id, **payment.dict())

@app.get("/health")
def health():
    return {"status": "payment-service healthy"}
