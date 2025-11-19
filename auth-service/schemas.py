from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum

class Role(str, Enum):
    user = "user"
    driver = "driver"
    admin = "admin"

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Role = Role.user
    vehicle: Optional[str] = None
    license_number: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
