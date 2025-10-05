import os
import uuid
import json
import asyncio
from fastapi import FastAPI
from database import database, metadata, engine
from models import notifications
from schemas import NotificationCreate, Notification
from events import publish_event
import boto3

# --- AWS / SQS Config ---
USE_AWS = os.getenv("USE_AWS", "False") == "True"
QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")  # Order Service SQS

if USE_AWS:
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))

# --- FastAPI App ---
app = FastAPI(title="Notification Service")


# --- Poll SQS Once ---
async def poll_sqs_once():
    """Poll SQS once and process only new messages (skip already processed orders)."""
    if not USE_AWS:
        return

    response = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=5,
        WaitTimeSeconds=0
    )
    messages = response.get("Messages", [])
    if not messages:
        print("No new messages in queue.")
        return

    for msg in messages:
        try:
            body = json.loads(msg["Body"])
            order_id = body.get("id")
            user_id = body.get("user_id")
            item_name = body.get("items", "your order")
            status = body.get("status", "pending")

            if not order_id:
                print("Skipping message without order_id:", body)
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # --- Check if this order already has a notification ---
            existing = await database.fetch_one(
                notifications.select().where(notifications.c.title == f"Order {order_id} Update")
            )

            if existing:
                print(f"Notification for order {order_id} already exists, skipping.")
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # --- Create new notification ---
            notification_id = str(uuid.uuid4())
            query = notifications.insert().values(
                id=notification_id,
                user_id=user_id,
                title=f"Order {order_id} Update",
                message=f"Your order {order_id} for {item_name} is {status}"
            )
            await database.execute(query)

            # --- Publish event ---
            await publish_event("notification.created", {
                "id": notification_id,
                "user_id": user_id,
                "title": f"Order {order_id} Update",
                "message": f"Your order {order_id} for {item_name} is {status}"
            })

            # --- Delete processed message from queue ---
            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=msg["ReceiptHandle"]
            )

            print(f" Processed new notification for order {order_id}")

        except Exception as e:
            print(f" Error processing message: {e}")
            # Don't delete message — it will retry later

# --- Startup / Shutdown ---
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)  # ensures table exists with order_id

    if USE_AWS:
        # Optional: periodic polling every 30 seconds
        async def periodic_poll():
            while True:
                await poll_sqs_once()
                await asyncio.sleep(30)

        asyncio.create_task(periodic_poll())


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# --- Manual polling endpoint ---
@app.post("/poll_notifications")
async def poll_notifications():
    """Manually trigger polling SQS for new orders."""
    await poll_sqs_once()
    return {"status": "Polling complete"}


# --- API Endpoints ---
@app.post("/notifications", response_model=Notification)
async def create_notification(notification: NotificationCreate):
    """Manually create a notification."""
    notification_id = str(uuid.uuid4())
    query = notifications.insert().values(
        id=notification_id,
        order_id=str(uuid.uuid4()),  # unique ID for manual notifications
        user_id=notification.user_id,
        title=notification.title,
        message=notification.message
    )
    await database.execute(query)

    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": notification.user_id,
        "title": notification.title,
        "message": notification.message
    })

    return Notification(id=notification_id, **notification.dict())


@app.get("/health")
def health():
    return {"status": "notification-service healthy"}
