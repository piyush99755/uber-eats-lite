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

sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION")) if USE_AWS else None

# --- FastAPI App ---
app = FastAPI(title="Notification Service")


async def process_order_event(order_event: dict):
    """Handle incoming order.created event and create a notification."""
    notification_id = str(uuid.uuid4())
    message = f"Your order {order_event['id']} with items {order_event['items']} has been placed!"

    # Save to DB
    query = notifications.insert().values(
        id=notification_id,
        user_id=order_event["user_id"],
        title=f"Order {order_event['id']} Update",
        message=message
    )
    await database.execute(query)

    # Publish notification.created event
    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": order_event["user_id"],
        "title": f"Order {order_event['id']} Update",
        "message": message
    })

    print(f"Processed notification {notification_id} for order {order_event['id']}")


async def poll_sqs():
    """Continuously poll SQS and process messages asynchronously."""
    if not USE_AWS:
        print("Running in local mode; skipping SQS consumer")
        return

    print("Notification Service SQS consumer started...")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10
            )
            messages = response.get("Messages", [])

            if messages:
                for msg in messages:
                    body = json.loads(msg["Body"])
                    await process_order_event(body)
                    # Delete message after processing
                    sqs.delete_message(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
            # Sleep only if no messages to avoid CPU hot-loop
            if not messages:
                await asyncio.sleep(2)

        except Exception as e:
            print(f"Error polling SQS: {e}")
            await asyncio.sleep(5)  # wait before retrying


# --- Startup / Shutdown ---
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    if USE_AWS:
        asyncio.create_task(poll_sqs())  # run consumer in background


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# --- Manual Polling Endpoint ---
@app.post("/poll_notifications")
async def poll_notifications():
    """Manually trigger polling SQS for new orders."""
    await poll_sqs()
    return {"status": "Polling complete"}


# --- API Endpoints ---
@app.post("/notifications", response_model=Notification)
async def create_notification(notification: NotificationCreate):
    """Manually create a notification."""
    notification_id = str(uuid.uuid4())
    query = notifications.insert().values(
        id=notification_id,
        order_id=str(uuid.uuid4()),
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
