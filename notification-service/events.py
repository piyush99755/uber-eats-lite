import os
import json
import asyncio
import aioboto3
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")

# Create reusable AWS session
session = aioboto3.Session()


async def handle_event(event_type: str, data: dict):
    """
    Generic event handler that prints notifications for all service events.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Universal print for all events
    print(f"\n[NOTIFY] 🕒 {timestamp} | Event: {event_type}")
    print(f"[NOTIFY] 📦 Payload: {json.dumps(data, indent=2)}")

    # Custom reactions per event type (optional)
    if event_type == "payment.processed":
        print(f"[NOTIFY] 💰 Payment paid for order {data['order_id']} by user {data['user_id']} (Amount: ${data['amount']})")
    elif event_type == "order.created":
        print(f"[NOTIFY] 🛒 New order created by user {data['user_id']} for item(s): {data['items']}")
    elif event_type == "driver.assigned":
        print(f"[NOTIFY] 🚗 Driver {data.get('driver_id', 'N/A')} assigned to order {data.get('order_id', 'N/A')}")
    elif event_type == "user.created":
        print(f"[NOTIFY] 👤 New user registered: {data.get('user_id', 'Unknown')}")
    else:
        print(f"[NOTIFY] 🔔 Unrecognized event type: {event_type}")

    print("-" * 80)


async def poll_notifications():
    """
    Poll Notification SQS for all incoming messages.
    """
    if not USE_AWS:
        print("[Notification Service] Local mode — skipping SQS polling.")
        while True:
            await asyncio.sleep(10)
        return

    print(f"[Notification Service] AWS mode — SQS polling started.")
    print(f"[Notification Service] Polling SQS: {NOTIFICATION_QUEUE_URL}")

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type", "unknown")
                        data = body.get("data", {})

                        await handle_event(event_type, data)

                        # Delete after processing
                        await sqs.delete_message(
                            QueueUrl=NOTIFICATION_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                    except Exception as e:
                        print(f"[ERROR] Failed to process message: {e}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)
