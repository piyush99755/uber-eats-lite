import asyncio
import os
import json
import uuid
from dotenv import load_dotenv
import aioboto3
from database import database
from models import notifications
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# In-memory deduplication set
processed_events = set()


async def save_notification(user_id: str, title: str, message: str):
    """Save notification in DB and publish notification.created event."""
    notification_id = str(uuid.uuid4())
    query = notifications.insert().values(
        id=notification_id,
        user_id=user_id,
        title=title,
        message=message
    )
    await database.execute(query)

    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": user_id,
        "title": title,
        "message": message
    })

    print(f"[NOTIFY] 🔔 {title} for user {user_id}")


async def handle_event(event_type: str, event_data: dict):
    """Handle incoming events and log to console with deduplication."""
    event_id = event_data.get("id") or event_data.get("order_id") or str(uuid.uuid4())

    # Skip if we've already processed this event
    if event_id in processed_events:
        return
    processed_events.add(event_id)

    if event_type == "order.created":
        user_id = event_data.get("user_id")
        order_id = event_data.get("id")
        print(f"[NOTIFY] 🛒 New order {order_id} placed by user {user_id}")

    elif event_type == "payment.processed":
        order_id = event_data.get("order_id")
        amount = event_data.get("amount")
        print(f"[NOTIFY] 💰 Payment processed for order {order_id} (Amount: {amount})")

    elif event_type == "driver.assigned":
        order_id = event_data.get("order_id")
        driver_id = event_data.get("driver_id")
        print(f"[NOTIFY] 🚗 Driver {driver_id} assigned to order {order_id}")

    elif event_type == "notification.created":
        user_id = event_data.get("user_id")
        title = event_data.get("title")
        print(f"[NOTIFY] 🔔 Notification created for user {user_id}: {title}")

    elif event_type == "user.created":
        name = event_data.get("name")
        print(f"[NOTIFY] 👋 Welcome new user: {name}!")

    else:
        print(f"[WARN] ⚠️ Unhandled event type: {event_type}")


async def poll_sqs():
    """Continuously poll Notification SQS for new messages with async client."""
    if not USE_AWS:
        print("[Consumer] Local mode active — waiting for simulated events...")
        while True:
            await asyncio.sleep(10)
        return

    session = aioboto3.Session()
    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print("[Notification Consumer] AWS mode enabled, polling SQS...")
        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                    MessageAttributeNames=["All"]
                )
                messages = response.get("Messages", [])

                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])

                        # Handle EventBridge wrapped messages
                        if "detail-type" in body and "detail" in body:
                            event_type = body["detail-type"]
                            event_data = body["detail"]
                            if isinstance(event_data, str):
                                event_data = json.loads(event_data)
                        else:
                            event_type = body.get("type")
                            event_data = body.get("data", {})

                        if event_type:
                            await handle_event(event_type, event_data)

                        # Delete message after processing
                        await sqs.delete_message(
                            QueueUrl=QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )

                    except Exception as e:
                        print(f"[ERROR] Failed to process message: {e}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)
