from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    id: Optional[str] = None           # auth-service can optionally send an existing ID
    name: str
    email: EmailStr
    role: Optional[str] = "user"       # default role

class User(UserCreate):
    id: str
