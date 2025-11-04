import os
import json
import asyncio
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()
processed_events = set()


# -------------------------------
# Event Handlers
# -------------------------------
async def handle_user_created(data: dict):
    print(f"[NOTIFY] 👤 User created: {data.get('id')} - {data.get('name')}")


async def handle_driver_created(data: dict):
    print(f"[NOTIFY] 🏎️ Driver created: {data.get('id')} - {data.get('name')} ({data.get('vehicle')})")


async def handle_order_created(data: dict):
    print(f"[NOTIFY] 🛒 Order created: {data.get('id')} by user {data.get('user_id')} "
          f"(Items: {data.get('items')}, Total: ${data.get('total')})")


async def handle_payment_processed(data: dict):
    print(f"[NOTIFY] 💰 Payment processed for order {data.get('order_id')} "
          f"by user {data.get('user_id')} (${data.get('amount')})")


async def handle_driver_assigned(data: dict):
    print(f"[NOTIFY] 🚗 Driver {data.get('driver_id')} assigned to order {data.get('order_id')}")


async def handle_unknown(event_type: str, data: dict):
    print(f"[NOTIFY] {event_type.upper()} -> {json.dumps(data)}")


EVENT_HANDLERS = {
    "user.created": handle_user_created,
    "driver.created": handle_driver_created,
    "order.created": handle_order_created,
    "payment.processed": handle_payment_processed,
    "driver.assigned": handle_driver_assigned
}


# -------------------------------
# Publish Event (for internal notifications)
# -------------------------------
async def publish_event(event_type: str, data: dict):
    """
    Optionally publish new events (like notification.created) to AWS.
    """
    try:
        if USE_AWS:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps({"type": event_type, "data": data})
                )
            async with session.client("events", region_name=AWS_REGION) as eventbridge:
                await eventbridge.put_events(
                    Entries=[{
                        "Source": "notification-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(data),
                        "EventBusName": EVENT_BUS
                    }]
                )
            print(f"[NOTIFY] ✅ Published {event_type} -> AWS")
        else:
            print(f"[LOCAL EVENT] {event_type}: {data}")
    except Exception as e:
        print(f"[WARN] Failed to publish event {event_type}: {e}")


# -------------------------------
# Poll SQS for incoming messages
# -------------------------------
async def poll_sqs():
    """Continuously poll SQS and process incoming events."""
    if not USE_AWS:
        print("[Notification Service] Local mode — skipping SQS polling.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Notification Service] Polling SQS: {QUEUE_URL}")

        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )

                messages = resp.get("Messages", [])
                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type", "unknown")
                        data = body.get("data", {})

                        event_id = data.get("id") or data.get("event_id")
                        if event_id in processed_events:
                            await sqs.delete_message(
                                QueueUrl=QUEUE_URL,
                                ReceiptHandle=msg["ReceiptHandle"]
                            )
                            continue
                        processed_events.add(event_id)

                        handler = EVENT_HANDLERS.get(event_type, handle_unknown)
                        if handler == handle_unknown:
                            await handler(event_type, data)
                        else:
                            await handler(data)

                        await sqs.delete_message(
                            QueueUrl=QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )

                    except Exception as e:
                        print(f"[ERROR] Failed to handle message: {e}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)
