# schemas.py
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime

class OrderCreate(BaseModel):
    user_id: str
    items: List[str]
    total: float

class Order(OrderCreate):
    id: str
    status: str
    driver_id: Optional[str] = None

class OrderUpdate(BaseModel):
    items: Optional[List[str]] = None
    total: Optional[float] = None
    status: Optional[str] = None
    driver_id: Optional[str] = None

class AssignDriver(BaseModel):
    driver_id: str

class EventLog(BaseModel):
    id: str
    event_type: str
    payload: Any
    source: str
    created_at: datetime
