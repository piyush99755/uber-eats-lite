import os
import json
import asyncio
from dotenv import load_dotenv
import aioboto3

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

# In-memory set to track processed event IDs and prevent duplicates
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
    print(f"[NOTIFY] 💰 Payment paid for order {data.get('order_id')} by user {data.get('user_id')} "
          f"(Amount: ${data.get('amount')})")

async def handle_driver_assigned(data: dict):
    print(f"[NOTIFY] 🚗 Driver assigned: {data.get('driver_id')} assigned to order {data.get('order_id')}")

# Default handler for unknown events
async def handle_unknown(event_type: str, data: dict):
    print(f"[NOTIFY] {event_type.upper()} -> {json.dumps(data)}")

# Map event types to handlers
EVENT_HANDLERS = {
    "user.created": handle_user_created,
    "driver.created": handle_driver_created,
    "order.created": handle_order_created,
    "payment.processed": handle_payment_processed,
    "driver.assigned": handle_driver_assigned
}

# -------------------------------
# Poll SQS and process events
# -------------------------------
async def poll_sqs():
    if not USE_AWS:
        print("[Notification Service] Local mode — waiting for events...")
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

                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type", "unknown")
                        data = body.get("data", {})

                        # Use event_id for deduplication
                        event_id = data.get("id") or data.get("event_id")
                        if event_id in processed_events:
                            # Already processed, delete message and skip
                            await sqs.delete_message(
                                QueueUrl=QUEUE_URL,
                                ReceiptHandle=msg["ReceiptHandle"]
                            )
                            continue
                        processed_events.add(event_id)

                        # Call the appropriate handler
                        handler = EVENT_HANDLERS.get(event_type, handle_unknown)
                        if handler == handle_unknown:
                            await handler(event_type, data)
                        else:
                            await handler(data)

                        # Delete message after processing
                        await sqs.delete_message(
                            QueueUrl=QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )

                    except Exception as e:
                        print(f"[ERROR] Failed to handle message: {e}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)

# -------------------------------
# Main entry point
# -------------------------------
if __name__ == "__main__":
    asyncio.run(poll_sqs())
