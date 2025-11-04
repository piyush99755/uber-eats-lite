import os
import json
import asyncio
import aioboto3
from dotenv import load_dotenv
from events import log_event_to_db

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
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
    print(f"[NOTIFY] 🤷 UNKNOWN EVENT {event_type} → {json.dumps(data, indent=2)}")


EVENT_HANDLERS = {
    "user.created": handle_user_created,
    "driver.created": handle_driver_created,
    "order.created": handle_order_created,
    "payment.processed": handle_payment_processed,
    "driver.assigned": handle_driver_assigned,
}

# -------------------------------
# Utility: Normalize incoming messages
# -------------------------------
def parse_event(raw_body: str) -> tuple[str, dict]:
    """
    Normalizes event payloads from both SQS and EventBridge.
    Returns (event_type, data)
    """
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        print(f"[WARN] Could not parse message body: {raw_body}")
        return "unknown", {}

    # Handle SQS-style events (from your other services)
    if "type" in parsed:
        return parsed["type"], parsed.get("data", {})

    # Handle EventBridge messages
    if "detail-type" in parsed or "DetailType" in parsed:
        event_type = parsed.get("detail-type") or parsed.get("DetailType")
        data = parsed.get("detail") or parsed.get("Detail") or {}
        return event_type, data

    # Handle fallback (maybe nested inside "Message")
    if "Message" in parsed:
        try:
            inner = json.loads(parsed["Message"])
            return parse_event(json.dumps(inner))
        except Exception:
            pass

    return "unknown", parsed


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
                    WaitTimeSeconds=10,
                )

                messages = resp.get("Messages", [])
                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        event_type, data = parse_event(msg["Body"])

                        # ✅ Log every incoming event to DB
                        await log_event_to_db(event_type, data, source_service="notification-service")

                        # Skip duplicate processing
                        event_id = data.get("id") or data.get("event_id") or msg.get("MessageId")
                        if event_id in processed_events:
                            await sqs.delete_message(
                                QueueUrl=QUEUE_URL,
                                ReceiptHandle=msg["ReceiptHandle"]
                            )
                            continue
                        processed_events.add(event_id)

                        # Handle event
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
                        print(f"[ERROR] Failed to handle message: {repr(e)}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {repr(e)}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_sqs())
