from pydantic import BaseModel

class OrderCreate(BaseModel):
    user_id: str
    items: str

class Order(OrderCreate):
    id: str
    status: str
