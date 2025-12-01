import os
import json
import aioboto3
from datetime import datetime
from uuid import uuid4
import httpx
import asyncio

# ───────────────────────────────────────────────────────────
# Environment
# ───────────────────────────────────────────────────────────
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
USER_QUEUE_URL = os.getenv("USER_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
ORDER_PAYMENT_QUEUE_URL = os.getenv("ORDER_PAYMENT_QUEUE_URL")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")

session = aioboto3.Session()

# ───────────────────────────────────────────────────────────
# WebSocket broadcast
# ───────────────────────────────────────────────────────────
connected_clients = set()

async def broadcast_payment_event(event: dict):
    """Send event to all connected WebSocket clients."""
    dead = []
    for ws in connected_clients:
        try:
            asyncio.create_task(ws.send_text(json.dumps(event)))
        except:
            dead.append(ws)
    for ws in dead:
        connected_clients.discard(ws)

# ───────────────────────────────────────────────────────────
# Publish event to AWS SQS or local endpoints
# ───────────────────────────────────────────────────────────
async def publish_event(event_type: str, payload: dict, trace_id: str = None):
    message_id = str(uuid4())
    message = {
        "event_id": message_id,
        "type": event_type,
        "data": {**payload, "event_id": message_id},
        "timestamp": datetime.utcnow().isoformat(),
        "trace_id": trace_id or "unknown"
    }

    if not USE_AWS:
        # Local delivery: webhook + WebSocket
        if event_type == "payment.completed":
            webhook_url = f"{ORDER_SERVICE_URL}/webhook/payment"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(webhook_url, json=message)
                print(f"[LOCAL EVENT → ORDER] {event_type} sent to {webhook_url}")
            except Exception as e:
                print(f"[LOCAL EVENT ERROR] {event_type}: {e}")

        try:
            await broadcast_payment_event(message)
            print(f"[LOCAL WS BROADCAST] {event_type}")
        except Exception as e:
            print(f"[LOCAL WS ERROR] {e}")
        return

    # AWS SQS delivery
    queue_urls = []
    if event_type == "payment.completed":
        if ORDER_PAYMENT_QUEUE_URL:
            queue_urls.append(ORDER_PAYMENT_QUEUE_URL)
        if DRIVER_QUEUE_URL:
            queue_urls.append(DRIVER_QUEUE_URL)
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
