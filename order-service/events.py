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
from ws_manager import manager  # New WebSocket manager

load_dotenv()

logger = logging.getLogger("order-service")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Target Queues
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()

# Map events to services
EVENT_TARGETS = {
    "order.created": ["Notification Service", "Driver Service", "Payment Service"],
    "order.updated": ["Notification Service", "Driver Service", "Payment Service"],
    "order.deleted": ["Notification Service", "Driver Service"],
}

SERVICE_QUEUE_MAP = {
    "Notification Service": NOTIFICATION_QUEUE_URL,
    "Driver Service": DRIVER_QUEUE_URL,
    "Payment Service": PAYMENT_QUEUE_URL,
}


async def publish_event(event_type: str, data: dict, trace_id: str = None):
    """
    Publish an event to:
    1. SSE clients (live UI updates)
    2. WebSocket clients (new WS manager)
    3. AWS SQS / EventBridge (if enabled)
    """
    event_time = datetime.utcnow().isoformat()
    event_payload = {
        "event_type": event_type,
        "payload": data,
        "trace_id": trace_id,
        "timestamp": event_time,
        "id": f"{event_type}_{datetime.utcnow().timestamp()}",  # UNIQUE EVENT ID
    }

    # --- Broadcast to SSE clients ---
    for queue in clients:
        try:
            await queue.put(event_payload)
        except Exception as e:
            logger.warning(f"[SSE ERROR] Failed to send event: {e}")

    # --- Broadcast to WebSocket clients ---
    await manager.broadcast(event_payload)

    # --- Local mode logging ---
    if not USE_AWS:
        logger.info(f"[LOCAL EVENT] {event_type}: {json.dumps(data, indent=2)}")
        return

    # --- AWS mode (SQS + EventBridge) ---
    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            for service_name in EVENT_TARGETS.get(event_type, []):
                queue_url = SERVICE_QUEUE_MAP.get(service_name)
                if not queue_url:
                    logger.warning(f"[WARN] {service_name} queue not set, skipping")
                    continue
                try:
                    await sqs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(event_payload),
                    )
                    logger.info(f"[SQS SENT → {service_name}] {event_type}")
                except Exception as e:
                    logger.warning(f"[SQS ERROR → {service_name}] {e}")

            # Optional EventBridge
            if EVENT_BUS and os.getenv("USE_EVENTBRIDGE", "false").lower() in ("true", "1", "yes"):
                try:
                    await eventbridge.put_events(
                        Entries=[{
                            "Source": "order-service",
                            "DetailType": event_type,
                            "Detail": json.dumps(data),
                            "EventBusName": EVENT_BUS,
                        }]
                    )
                    logger.info(f"[EventBridge] Published {event_type}")
                except Exception as e:
                    logger.warning(f"[EventBridge ERROR] {e}")

    except Exception as e:
        logger.error(f"[EVENT ERROR] Failed to publish {event_type}: {e}")


async def log_event_to_db(event_type: str, data: dict, source_service: str):
    """
    Stores event_id in processed_events for idempotency.
    """
    event_id = data.get("id") or data.get("event_id")
    if not event_id:
        logger.warning(f"[WARN] Missing event ID for {event_type}")
        return True  # process anyway

    # Check for duplicates
    query_check = processed_events.select().where(processed_events.c.event_id == event_id)
    existing = await database.fetch_one(query_check)

    if existing:
        logger.info(f"[SKIP] Duplicate {event_type} ({event_id}) — already handled by {source_service}")
        return False

    # Insert new event record
    query_insert = processed_events.insert().values(
        event_id=event_id,
        event_type=event_type,
        source_service=source_service,
        processed_at=datetime.utcnow(),
    )
    await database.execute(query_insert)
    logger.info(f"[LOGGED] {event_type} ({event_id}) from {source_service}")
    return True
