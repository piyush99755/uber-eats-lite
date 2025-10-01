from pydantic import BaseModel

class NotificationCreate(BaseModel):
    title: str
    message: str
    user_id: str  

class Notification(BaseModel):
    id: str
    title: str
    message: str
    user_id: str
