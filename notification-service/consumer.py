import asyncio
import os
import json
from dotenv import load_dotenv
import boto3
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False") == "True"
QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")

if USE_AWS:
    if not QUEUE_URL:
        raise ValueError("NOTIFICATION_QUEUE_URL is not set for consumer.")
    sqs = boto3.client("sqs")
    print("[Notification Consumer] AWS mode enabled, polling SQS...")
else:
    print("[Notification Consumer] Running in LOCAL mode, no SQS polling.")


async def handle_event(event_type: str, event_data: dict):
    """Log incoming events for notification."""
    if event_type == "order.created":
        user_id = event_data.get("user_id")
        print(f"[NOTIFY] New order placed by user {user_id}")
    elif event_type == "payment.processed":
        order_id = event_data.get("order_id")
        print(f"[NOTIFY] Payment processed for order {order_id}")
    elif event_type == "driver.assigned":
        order_id = event_data.get("order_id")
        driver_id = event_data.get("driver_id")
        print(f"[NOTIFY] Driver {driver_id} assigned to order {order_id}")
    else:
        print(f"[NOTIFY] Unhandled event: {event_type}")


async def poll_sqs():
    """Continuously poll SQS for new messages."""
    if not USE_AWS:
        print("[Consumer] Local mode active — waiting for simulated events...")
        while True:
            await asyncio.sleep(10)
        return

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
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
                    event_type = body.get("type")
                    event_data = body.get("data", {})
                    if event_type:
                        await handle_event(event_type, event_data)

                    # Delete processed message
                    sqs.delete_message(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
                except Exception as e:
                    print(f"[ERROR] Failed to process message: {e}")

        except Exception as e:
            print(f"[ERROR] Polling failed: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_sqs())
