from pydantic import BaseModel
from typing import Any
from datetime import datetime

# ------------------------
# Order Schemas
# ------------------------
class OrderCreate(BaseModel):
    user_id: str
    items: str
    total: float

class Order(OrderCreate):
    id: str
    status: str

class AssignDriver(BaseModel):
    driver_id: str

# ------------------------
# Event Log Schema
# ------------------------
class EventLog(BaseModel):
    id: str
    event_type: str
    payload: Any
    source: str
    created_at: datetime


