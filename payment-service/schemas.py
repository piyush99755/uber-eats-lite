from pydantic import BaseModel

class PaymentCreate(BaseModel):
    order_id: str
    amount: float

class Payment(PaymentCreate):
    id: str
    status: str
