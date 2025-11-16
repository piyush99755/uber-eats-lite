# payment-service/events.py
import os
import json
import aioboto3
from datetime import datetime
import httpx
from uuid import uuid4

# ───────────────────────────────────────────────────────────
# Environment
# ───────────────────────────────────────────────────────────
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")           # internal payments
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
USER_QUEUE_URL = os.getenv("USER_QUEUE_URL")
ORDER_PAYMENT_QUEUE_URL = os.getenv("ORDER_PAYMENT_QUEUE_URL")  # queue for order-service to receive payment.completed

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")

session = aioboto3.Session()


async def publish_event(event_type: str, payload: dict, trace_id: str = None):
    """
    Publishes a cloud event to:
        - LOCAL dev → HTTP webhook (order-service)
        - AWS production → SQS queue
    """

    # ───────────────────────────────────────────────────────────
    # Build event envelope (CloudEvent-like)
    # ───────────────────────────────────────────────────────────
    message = {
        "event_id": str(uuid4()),        # ✅ unique ID for each event
        "type": event_type,
        "data": payload,
        "timestamp": datetime.utcnow().isoformat(),
        "trace_id": trace_id or "unknown"
    }

    # ───────────────────────────────────────────────────────────
    # LOCAL MODE: HTTP webhook → order-service
    # ───────────────────────────────────────────────────────────
    if not USE_AWS:
        webhook_url = f"{ORDER_SERVICE_URL}/webhook/payment"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(webhook_url, json=message)
            print(f"[LOCAL EVENT → ORDER] {event_type} sent to {webhook_url} (event_id={message['event_id']})")
        except Exception as e:
            print(f"[LOCAL EVENT ERROR] {event_type}: {e}")
        return

    # ───────────────────────────────────────────────────────────
    # AWS MODE: Select queue by topic
    # ───────────────────────────────────────────────────────────
    if event_type == "payment.completed":
        # route payment.completed to order-service queue
        queue_url = ORDER_PAYMENT_QUEUE_URL
    elif event_type.startswith("payment."):
        # other payment.* events stay in payment-service queue
        queue_url = PAYMENT_QUEUE_URL
    elif event_type.startswith("notify."):
        queue_url = NOTIFICATION_QUEUE_URL
    else:
        queue_url = USER_QUEUE_URL

    if not queue_url:
        print(f"[SKIP] No SQS queue configured for event: {event_type}")
        return

    # ───────────────────────────────────────────────────────────
    # Publish to SQS
    # ───────────────────────────────────────────────────────────
    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            await sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message),
            )
        print(f"[SQS EVENT] {event_type} → {queue_url} (event_id={message['event_id']})")
    except Exception as e:
        print(f"[SQS ERROR] {event_type}: {e}")
