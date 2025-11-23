# --- order-service/events.py ---
import os
import json
import aioboto3
import logging
from datetime import datetime
from dotenv import load_dotenv
from database import database
from models import processed_events
from sse_clients import clients
from ws_manager import manager
import uuid

load_dotenv()

logger = logging.getLogger("order-service")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
ORDER_QUEUE_URL = os.getenv("ORDER_PAYMENT_QUEUE_URL")  # order-service internal queue
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()

# Explicit routing
EVENT_TARGETS = {
    "order.created": ["Notification Service", "Driver Service", "Payment Service"],
    "order.updated": ["Driver Service", "Notification Service"],  # send to driver for assignment
    "order.deleted": ["Notification Service", "Driver Service"],
    "payment.completed": ["Order Service"],  # only order-service
}

SERVICE_QUEUE_MAP = {
    "Notification Service": NOTIFICATION_QUEUE_URL,
    "Driver Service": DRIVER_QUEUE_URL,
    "Payment Service": PAYMENT_QUEUE_URL,
    "Order Service": ORDER_QUEUE_URL,
}


import uuid
from datetime import datetime

async def publish_order_created_event(order: dict, trace_id: str = None):
    """
    Publish an 'order.created' event to all relevant services:
    Notification, Driver, Payment.
    Ensures order_id and other essential fields are always included.
    """
    order_id = order.get("id")
    if not order_id:
        logger.error("[publish_order_created_event] ❌ Missing order id in order object")
        return

    # Build payload with essential order info
    event_data = {
        "order_id": order_id,
        "user_id": order.get("user_id"),
        "status": order.get("status", "pending"),
        "payment_status": order.get("payment_status", "unpaid"),
        "driver_id": order.get("driver_id"),
        "items": order.get("items", []),
        "total_amount": order.get("total_amount"),
        "event_id": f"order.created_{uuid.uuid4()}"  # ✅ guaranteed unique
    }

    # Build event payload wrapper
    event_payload = {
        "event_type": "order.created",
        "payload": event_data,
        "trace_id": trace_id,
        "timestamp": datetime.utcnow().isoformat(),
        "id": event_data["event_id"]
    }

    # Broadcast to WebSocket and SSE clients
    for queue in clients:
        try:
            await queue.put(event_payload)
        except Exception as e:
            logger.warning(f"[SSE ERROR] {e}")

    await manager.broadcast(event_payload)

    if not USE_AWS:
        logger.info(f"[LOCAL EVENT] {event_payload}")
        return

    # Send to SQS queues
    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            for service_name in EVENT_TARGETS.get("order.created", []):
                queue_url = SERVICE_QUEUE_MAP.get(service_name)
                if not queue_url:
                    logger.warning(f"[WARN] Missing queue for {service_name}")
                    continue

                try:
                    await sqs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(event_payload)
                    )
                    logger.info(f"[SQS → {service_name}] order.created (event_id={event_payload['id']})")
                except Exception as e:
                    logger.warning(f"[SQS ERROR → {service_name}] {e}")

    except Exception as e:
        logger.error(f"[EVENT ERROR] {e}")


async def log_event_to_db(event_type: str, data: dict, source_service: str):
    """ Idempotency storage for processed events """
    event_id = data.get("id") or data.get("event_id")
    if not event_id:
        return True

    existing = await database.fetch_one(
        processed_events.select().where(processed_events.c.event_id == event_id)
    )

    if existing:
        logger.info(f"[SKIP] Duplicate {event_type} ({event_id})")
        return False

    await database.execute(
        processed_events.insert().values(
            event_id=event_id,
            event_type=event_type,
            source_service=source_service,
            processed_at=datetime.utcnow(),
        )
    )

    logger.info(f"[LOGGED] {event_type} ({event_id})")
    return True
