# driver-service/events.py
import os
import json
import aioboto3
import logging
from datetime import datetime
from dotenv import load_dotenv
from database import database

load_dotenv()

logger = logging.getLogger("driver-service")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# support both names (env might use ORDER_QUEUE_URL or ORDER_SERVICE_QUEUE)
ORDER_QUEUE_URL = os.getenv("ORDER_QUEUE_URL") or os.getenv("ORDER_SERVICE_QUEUE")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()


async def broadcast_ws_event_stub(event_type: str, data: dict):
    # placeholder — original code had websocket clients set, if you use it keep same
    return


async def publish_event(event_type: str, data: dict, trace_id: str = None, broadcast_ws: bool = True):
    """
    Publish an event to configured SQS queues (Order / Notification / Payment).
    Ensures an event_id exists and injects it into payload for consumers.
    """
    event_time = datetime.utcnow().isoformat()
    event_id = data.get("event_id") or data.get("id") or f"{event_type}_{datetime.utcnow().timestamp()}"
    # ensure payload contains event_id for downstream idempotency
    data_with_id = dict(data)
    data_with_id.setdefault("event_id", event_id)

    message_body = {
        "type": event_type,
        "data": data_with_id,
        "source": "driver-service",
        "timestamp": event_time,
        "event_id": event_id,
        "trace_id": trace_id,
    }

    # broadcast to any local WS clients if you have them
    if broadcast_ws:
        try:
            await broadcast_ws_event_stub(event_type, data_with_id)
        except Exception:
            logger.debug("[WS] broadcast skipped / failed")

    if not USE_AWS:
        logger.info(f"[LOCAL EVENT] {event_type} -> {json.dumps(data_with_id)}")
        return True

    sent_any = False
    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            targets = [
                ("Order Service", ORDER_QUEUE_URL),
                ("Notification Service", NOTIFICATION_QUEUE_URL),
                ("Payment Service", PAYMENT_QUEUE_URL),
            ]

            for name, url in targets:
                if not url:
                    logger.debug(f"[SQS SKIP] {name} queue not configured")
                    continue
                try:
                    await sqs.send_message(QueueUrl=url, MessageBody=json.dumps(message_body))
                    logger.info(f"[SQS SENT → {name}] {event_type} (event_id={event_id})")
                    sent_any = True
                except Exception as e:
                    logger.warning(f"[SQS ERROR → {name}] Failed to send {event_type}: {e}")

            # optional EventBridge
            if EVENT_BUS:
                try:
                    await eventbridge.put_events(
                        Entries=[{
                            "Source": "driver-service",
                            "DetailType": event_type,
                            "Detail": json.dumps(data_with_id),
                            "EventBusName": EVENT_BUS,
                        }]
                    )
                    logger.info(f"[EventBridge] Published {event_type} (event_id={event_id})")
                except Exception as e:
                    logger.warning(f"[EventBridge ERROR] {e}")

    except Exception as e:
        logger.error(f"[EVENT ERROR] Failed to publish {event_type}: {e}")
        return False

    return sent_any


async def log_event_to_db(event_type: str, data: dict, source_service: str):
    """
    Logs event_id to processed_events table for idempotency.
    Returns True if new event, False if duplicate (so caller can skip processing).
    """
    from models import processed_events  # local import to avoid cycles
    event_id = data.get("event_id") or data.get("id")
    if not event_id:
        logger.warning(f"[WARN] Event missing ID → {event_type}")
        return True

    query_check = processed_events.select().where(processed_events.c.event_id == event_id)
    existing = await database.fetch_one(query_check)
    if existing:
        logger.info(f"[SKIP] Duplicate event ({event_id}) from {source_service}")
        return False

    query_insert = processed_events.insert().values(
        event_id=event_id,
        event_type=event_type,
        source_service=source_service,
        processed_at=datetime.utcnow(),
    )
    await database.execute(query_insert)
    logger.info(f"[LOGGED] {event_type} ({event_id}) from {source_service}")
    return True
