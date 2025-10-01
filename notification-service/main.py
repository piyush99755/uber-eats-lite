from fastapi import FastAPI, HTTPException
from schemas import NotificationCreate, Notification
from models import notifications  # your SQLAlchemy table
from database import database, metadata, engine
from uuid import uuid4

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
    query = notifications.insert().values(
        id=notification_id,
        title=notification.title,
        message=notification.message,
        user_id=notification.user_id
    )
    await database.execute(query)
    return Notification(id=notification_id, **notification.dict())

@app.get("/notifications")
async def list_notifications():
    query = notifications.select()
    return await database.fetch_all(query)
