from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import notifications
from schemas import NotificationCreate, Notification
from database import database, metadata, engine
from events import publish_event

app = FastAPI(title="Notification Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/notifications", response_model=Notification)
async def create_notification(notification: NotificationCreate):
    notification_id = str(uuid4())
    query = notifications.insert().values(id=notification_id, user_id=notification.user_id, message=notification.message)
    await database.execute(query)
    
    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": notification.user_id,
        "message": notification.message
    })
    
    return Notification(id=notification_id, **notification.dict())

@app.get("/health")
def health():
    return {"status": "notification-service healthy"}
