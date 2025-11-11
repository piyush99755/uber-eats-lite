# payment-service/events.py
import os
import json
import aioboto3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Queue URLs
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
ORDER_SERVICE_QUEUE = os.getenv("ORDER_SERVICE_QUEUE")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")

session = aioboto3.Session()


async def publish_event(event_type: str, payload: dict):
    """
    Publish event to SQS:
      - payment.* → send to ORDER_SERVICE_QUEUE (so order-service updates status)
      - notify.* or others → send to NOTIFICATION_QUEUE_URL
      - fallback → PAYMENT_QUEUE_URL
    """

    message = {
        "id": payload.get("order_id") or f"evt_{datetime.utcnow().timestamp()}",
        "type": event_type,
        "data": payload,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {payload}")
        return

    # pick destination queue
    if event_type.startswith("payment."):
        target_queue = ORDER_SERVICE_QUEUE
    elif event_type.startswith("notify."):
        target_queue = NOTIFICATION_QUEUE_URL
    else:
        target_queue = PAYMENT_QUEUE_URL or ORDER_SERVICE_QUEUE

    if not target_queue:
        print(f"[WARN] No target queue for {event_type}")
        return

    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            await sqs.send_message(
                QueueUrl=target_queue,
                MessageBody=json.dumps(message)
            )
        print(f"[SQS SENT] {event_type} → {target_queue}")
    except Exception as e:
        print(f"[SQS ERROR] Could not send {event_type}: {e}")
