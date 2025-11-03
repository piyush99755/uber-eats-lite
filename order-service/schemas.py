# schemas.py
from pydantic import BaseModel
from typing import List, Any
from datetime import datetime

class OrderCreate(BaseModel):
    user_id: str
    items: List[str]   # ✅ list instead of string
    total: float

class Order(OrderCreate):
    id: str
    status: str

class AssignDriver(BaseModel):
    driver_id: str

class EventLog(BaseModel):
    id: str
    event_type: str
    payload: Any
    source: str
    created_at: datetime
