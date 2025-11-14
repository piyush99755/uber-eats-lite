from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class DriverBase(BaseModel):
    name: str
    vehicle_type: str
    license_number: str

class DriverCreate(DriverBase):
    pass

class Driver(DriverBase):
    id: str

    class Config:
        orm_mode = True

class NotificationCreate(BaseModel):
    driver_id: str
    title: str
    message: str

class Notification(NotificationCreate):
    id: Optional[str] = None
    created_at: Optional[datetime] = None