import os
import json
import aioboto3
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Environment configs
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")

# Create reusable AWS session
session = aioboto3.Session()


async def publish_event(event_type: str, data: dict):
    """
    Publish an event to AWS SQS (if USE_AWS=True), otherwise log locally.
    """
    event_payload = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    }

    if USE_AWS:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MessageBody=json.dumps(event_payload)
                )
            print(f"[EVENT] ✅ Published event to SQS → {event_type}")
        except Exception as e:
            print(f"[EVENT] ❌ Failed to publish event '{event_type}' to SQS: {e}")
    else:
        # Local development mode — just print the event
        print(f"\n[EVENT] 💡 Local mode — Event simulated:")
        print(json.dumps(event_payload, indent=2))


async def handle_event(event_type: str, data: dict):
    """
    Generic handler that reacts to events (used by consumer/polling side).
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[NOTIFY] 🕒 {timestamp} | Event: {event_type}")
    print(f"[NOTIFY] 📦 Payload: {json.dumps(data, indent=2)}")

    # Optional: custom reactions to specific events
    if event_type == "payment.processed":
        print(f"[NOTIFY] 💰 Payment processed for order {data.get('order_id')} (${data.get('amount')})")
    elif event_type == "order.created":
        print(f"[NOTIFY] 🛒 Order created by user {data.get('user_id')}")
    elif event_type == "driver.created":
        print(f"[NOTIFY] 🏎️ New driver added: {data.get('name')} ({data.get('vehicle')})")
    elif event_type == "user.created":
        print(f"[NOTIFY] 👤 New user registered: {data.get('name')}")
    elif event_type == "driver.assigned":
        print(f"[NOTIFY] 🚗 Driver {data.get('driver_id')} assigned to order {data.get('order_id')}")
    else:
        print(f"[NOTIFY] 🔔 Unrecognized event type: {event_type}")

    print("-" * 80)


# Optional: for standalone testing
if __name__ == "__main__":
    async def _test():
        test_event = {
            "id": "123",
            "user_id": "u001",
            "title": "Welcome!",
            "message": "Your account has been created."
        }
        await publish_event("notification.created", test_event)

    asyncio.run(_test())
