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
    "payment.completed": ["Order Service", "Driver Service"],  # only order-service
}

SERVICE_QUEUE_MAP = {
    "Notification Service": NOTIFICATION_QUEUE_URL,
    "Driver Service": DRIVER_QUEUE_URL,
    "Payment Service": PAYMENT_QUEUE_URL,
    "Order Service": ORDER_QUEUE_URL,
}


import uuid
from datetime import datetime

async def publish_event(event_type: str, data: dict, trace_id: str = None):
    event_payload = {
        "type": event_type,
        "event_id": str(data.get("event_id") or uuid.uuid4()),
        "data": data,
        "trace_id": trace_id,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # SSE
    for queue in clients:
        try:
            await queue.put(event_payload)
        except Exception as e:
            logger.warning(f"[SSE ERROR] {e}")

    # WS
    try:
        await manager.broadcast(event_payload)
    except Exception as e:
        logger.warning(f"[WebSocket ERROR] {e}")

    # SQS
    if USE_AWS:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                targets = EVENT_TARGETS.get(event_type, [])
                for service_name in targets:
                    queue_url = SERVICE_QUEUE_MAP.get(service_name)
                    if not queue_url:
                        logger.warning(f"[WARN] Missing queue for {service_name}")
                        continue
                    try:
                        await sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event_payload))
                        logger.info(f"[SQS → {service_name}] {event_type} event_id={event_payload['event_id']}")
                    except Exception as e:
                        logger.warning(f"[SQS ERROR → {service_name}] {e}")
        except Exception as e:
            logger.error(f"[EVENT ERROR] {e}")


async def publish_order_created_event(order: dict, trace_id: str = None):
    """
    Publish an 'order.created' event to:
    - SSE clients
    - WebSocket clients
    - SQS queues (Driver, Notification, Payment)

    FORMAT (required by driver-service):
    {
        "type": "order.created",
        "event_id": "uuid",
        "data": { ... }
    }
    """

    order_id = order.get("id")
    if not order_id:
        logger.error("[publish_order_created_event] ❌ Missing order id in order object")
        return

    # ---- BUILD THE DATA PAYLOAD ----
    data = {
        "order_id": order_id,
        "user_id": order.get("user_id"),
        "user_name": order.get("user_name"),      # if provided
        "status": order.get("status", "pending"),
        "payment_status": order.get("payment_status", "unpaid"),
        "driver_id": order.get("driver_id"),
        "driver_name": order.get("driver_name"),  # NEW — supports frontend
        "items": order.get("items", []),
        "total_amount": order.get("total_amount"),
        "timestamp": datetime.utcnow().isoformat(),
    }

    # ---- WRAP IN THE STANDARD EVENT ENVELOPE ----
    event_payload = {
        "type": "order.created",                   # REQUIRED by driver-service
        "event_id": str(uuid.uuid4()),             # Universal event ID
        "data": data,
        "trace_id": trace_id,
        "timestamp": data["timestamp"],
    }

    # ---- BROADCAST TO SSE CLIENTS ----
    for queue in clients:
        try:
            await queue.put(event_payload)
        except Exception as e:
            logger.warning(f"[SSE ERROR] {e}")

    # ---- BROADCAST TO WEBSOCKET CLIENTS ----
    try:
        await manager.broadcast(event_payload)
    except Exception as e:
        logger.warning(f"[WebSocket ERROR] {e}")

    # ---- LOCAL DEV MODE ----
    if not USE_AWS:
        logger.info(f"[LOCAL EVENT EMIT] {event_payload}")
        return

    # ---- SEND TO SQS TARGET SERVICES ----
    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            targets = EVENT_TARGETS.get("order.created", [])

            for service_name in targets:
                queue_url = SERVICE_QUEUE_MAP.get(service_name)

                if not queue_url:
                    logger.warning(f"[WARN] Missing queue for {service_name}")
                    continue

                try:
                    await sqs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(event_payload)
                    )
                    logger.info(
                        f"[SQS → {service_name}] order.created event_id={event_payload['event_id']}"
                    )
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
