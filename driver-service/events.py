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

# Queues
ORDER_QUEUE_URL = os.getenv("ORDER_QUEUE_URL")  # driver events → order-service
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")  # optional if needed
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()


async def broadcast_ws_event_stub(event_type: str, data: dict):
    # placeholder — optional WS broadcast
    return


async def publish_event(event_type: str, data: dict, trace_id: str = None, broadcast_ws: bool = True):
    """
    Publish an event to configured queues (Order / Notification / Payment).
    Ensures event_id exists and injects it into payload for idempotency.
    """
    event_time = datetime.utcnow().isoformat()
    event_id = data.get("event_id") or data.get("id") or f"{event_type}_{datetime.utcnow().timestamp()}"
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

    # optional WS broadcast
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

            # Decide which queues to send each event to
            targets = []

            if event_type.startswith("driver."):
                # Driver events mainly go to order-service queue and optionally notification
                if ORDER_QUEUE_URL:
                    targets.append(("Order Service", ORDER_QUEUE_URL))
                if NOTIFICATION_QUEUE_URL:
                    targets.append(("Notification Service", NOTIFICATION_QUEUE_URL))

            elif event_type.startswith("payment.") or event_type.startswith("order."):
                # For driver-service emitting downstream events if needed
                if PAYMENT_QUEUE_URL:
                    targets.append(("Payment Service", PAYMENT_QUEUE_URL))

            # send to SQS queues
            for name, url in targets:
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


