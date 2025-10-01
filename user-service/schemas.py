from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    name: str
    email: str

class User(UserCreate):
    id: str
