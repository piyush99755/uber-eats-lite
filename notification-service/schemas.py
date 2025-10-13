from pydantic import BaseModel
from typing import Optional

class NotificationCreate(BaseModel):
    title: str
    message: str
    user_id: str
    order_id: Optional[str] = None  # <-- optional for flexibility

class Notification(BaseModel):
    id: str
    title: str
    message: str
    user_id: str
    order_id: Optional[str] = None  # <-- also include for response consistency
