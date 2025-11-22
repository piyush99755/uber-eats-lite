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
ORDER_PAYMENT_QUEUE_URL = os.getenv("ORDER_PAYMENT_QUEUE_URL")  # order-service queue
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")                # driver-service queue

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")

session = aioboto3.Session()


async def publish_event(event_type: str, payload: dict, trace_id: str = None):
    message_id = str(uuid4())

    message = {
        "event_id": message_id,        # ✅ top-level event ID
        "type": event_type,
        "data": {**payload, "event_id": message_id},  # 🔹 inject into payload
        "timestamp": datetime.utcnow().isoformat(),
        "trace_id": trace_id or "unknown"
    }

    if not USE_AWS:
        webhook_url = f"{ORDER_SERVICE_URL}/webhook/payment"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(webhook_url, json=message)
            print(f"[LOCAL EVENT → ORDER] {event_type} sent to {webhook_url} (event_id={message_id})")
        except Exception as e:
            print(f"[LOCAL EVENT ERROR] {event_type}: {e}")
        return

    # Determine SQS queues
    queue_urls = []
    if event_type == "payment.completed":
        if ORDER_PAYMENT_QUEUE_URL:
            queue_urls.append(ORDER_PAYMENT_QUEUE_URL)   # for order-service
        if DRIVER_QUEUE_URL:
            queue_urls.append(DRIVER_QUEUE_URL)          # for driver-service
        if PAYMENT_QUEUE_URL:
            queue_urls.append(PAYMENT_QUEUE_URL) 
    elif event_type.startswith("payment."):
        if PAYMENT_QUEUE_URL:
            queue_urls.append(PAYMENT_QUEUE_URL)
    elif event_type.startswith("notify."):
        if NOTIFICATION_QUEUE_URL:
            queue_urls.append(NOTIFICATION_QUEUE_URL)
    else:
        if USER_QUEUE_URL:
            queue_urls.append(USER_QUEUE_URL)

    if not queue_urls:
        print(f"[SKIP] No SQS queue configured for event: {event_type}")
        return

    for q_url in queue_urls:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=q_url,
                    MessageBody=json.dumps(message),
                )
            print(f"[SQS EVENT] {event_type} → {q_url} (event_id={message_id})")
        except Exception as e:
            print(f"[SQS ERROR] {event_type} → {q_url}: {e}")
