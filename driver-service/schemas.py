from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class DriverBase(BaseModel):
    name: str
    vehicle: str         
    license_number: str

class DriverCreate(DriverBase):
    pass

class Driver(DriverBase):
    id: str
    status: str           

    class Config:
        orm_mode = True#
        
class VehicleUpdate(BaseModel):
    vehicle: str