# consumer.py
import os
import json
import asyncio
import aioboto3
from dotenv import load_dotenv
from events import log_event_to_db
from trace import get_or_create_trace_id
from event_handlers import format_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()
processed_events = set()

# -------------------------------
# Event Handlers
# -------------------------------
async def handle_user_created(data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event('user.created', data, trace_id)}")

async def handle_driver_created(data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event('driver.created', data, trace_id)}")

async def handle_order_created(data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event('order.created', data, trace_id)}")

async def handle_payment_processed(data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event('payment.processed', data, trace_id)}")

async def handle_driver_assigned(data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event('delivery.assigned', data, trace_id)}")

async def handle_unknown(event_type: str, data: dict, trace_id: str | None = None):
    print(f"[NOTIFY] {format_event(event_type, data, trace_id)}")

EVENT_HANDLERS = {
    "user.created": handle_user_created,
    "driver.created": handle_driver_created,
    "order.created": handle_order_created,
    "payment.processed": handle_payment_processed,
    "delivery.assigned": handle_driver_assigned,
}

# -------------------------------
# Utility: Normalize incoming messages
# -------------------------------
def parse_event(raw_body: str) -> tuple[str, dict]:
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        print(f"[WARN] Could not parse message body: {raw_body}")
        return "unknown", {}

    # SQS-style
    if "type" in parsed:
        return parsed["type"], parsed.get("data", {})

    # EventBridge style
    if "detail-type" in parsed or "DetailType" in parsed:
        event_type = parsed.get("detail-type") or parsed.get("DetailType")
        data = parsed.get("detail") or parsed.get("Detail") or {}
        return event_type, data

    # Nested "Message"
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
async def poll_sqs(EVENTS_PROCESSED=None, EVENTS_FAILED=None):
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
                    MessageAttributeNames=["All"]
                )

                messages = resp.get("Messages", [])
                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        event_type, data = parse_event(msg["Body"])

                        # ---------------------------
                        # Assign / propagate trace_id
                        # ---------------------------
                        trace_id = get_or_create_trace_id(
                            msg.get("MessageAttributes", {}).get("trace_id", {}).get("StringValue")
                        )
                        data['trace_id'] = trace_id

                        # ---------------------------
                        # Log event to DB
                        # ---------------------------
                        await log_event_to_db(event_type, data, source_service="notification-service", trace_id=trace_id)

                        # ---------------------------
                        # Increment metrics
                        # ---------------------------
                        if EVENTS_PROCESSED:
                            EVENTS_PROCESSED.labels(event_type=event_type).inc()

                        # ---------------------------
                        # Skip duplicates
                        # ---------------------------
                        event_id = data.get("id") or data.get("event_id") or msg.get("MessageId")
                        if event_id in processed_events:
                            await sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                            continue
                        processed_events.add(event_id)

                        # ---------------------------
                        # Handle event
                        # ---------------------------
                        handler = EVENT_HANDLERS.get(event_type, handle_unknown)
                        if handler == handle_unknown:
                            await handler(event_type, data, trace_id=trace_id)
                        else:
                            await handler(data, trace_id=trace_id)

                        # ---------------------------
                        # Delete message after processing
                        # ---------------------------
                        await sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

                    except Exception as e:
                        print(f"[ERROR] Failed to handle message [{trace_id}]: {repr(e)}")
                        if EVENTS_FAILED:
                            EVENTS_FAILED.labels(event_type=event_type).inc()

            except Exception as e:
                print(f"[ERROR] Polling failed: {repr(e)}")
                await asyncio.sleep(5)

# -------------------------------
# Standalone runner for local testing
# -------------------------------
if __name__ == "__main__":
    import prometheus_client
    EVENTS_PROCESSED = prometheus_client.Counter('events_processed_total', 'Total events processed', ['event_type'])
    EVENTS_FAILED = prometheus_client.Counter('events_failed_total', 'Total events failed', ['event_type'])
    asyncio.run(poll_sqs(EVENTS_PROCESSED, EVENTS_FAILED))
