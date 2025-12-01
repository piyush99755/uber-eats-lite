# driver-service/events.py
import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any

import aioboto3

load_dotenv()

logger = logging.getLogger("driver-service.events")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

ORDER_QUEUE_URL = os.getenv("ORDER_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()

# Optional WebSocket broadcast
try:
    from ws_manager import broadcast_to_connected_clients
except ImportError:
    broadcast_to_connected_clients = None


async def broadcast_ws_event(event_type: str, data: Dict[str, Any]):
    """
    Broadcast event to connected WebSocket clients.
    Safe fallback if WS manager is missing.
    """
    if not broadcast_to_connected_clients:
        return
    try:
        await broadcast_to_connected_clients(event_type, data)
        logger.info(f"[WS BROADCAST] Event '{event_type}' sent")
    except Exception as e:
        logger.warning(f"[WS BROADCAST ERROR] {e}")


async def publish_event(
    event_type: str,
    data: Dict[str, Any],
    trace_id: Optional[str] = None,
    broadcast_ws: bool = True
) -> bool:
    """
    Publish an event locally (log), via SQS, EventBridge, and optionally WS.
    Always adds event_id and timestamp.
    """
    now_iso = datetime.utcnow().isoformat()
    event_id = data.get("event_id") or f"{event_type}-{datetime.utcnow().timestamp()}"

    data_with_id = dict(data)
    data_with_id["event_id"] = event_id

    body = {
        "type": event_type,
        "data": data_with_id,
        "event_id": event_id,
        "timestamp": now_iso,
        "source": "driver-service",
        "trace_id": trace_id,
    }

    # WebSocket broadcast
    if broadcast_ws:
        await broadcast_ws_event(event_type, data_with_id)

    # Local logging mode (no AWS)
    if not USE_AWS:
        logger.info(f"[LOCAL EVENT] {event_type}: {json.dumps(data_with_id)}")
        return True

    sent = False

    # AWS clients
    async with session.client("sqs", region_name=AWS_REGION) as sqs, \
               session.client("events", region_name=AWS_REGION) as evb:

        targets = []

        # Driver-related events → Order & Notification queues
        if event_type.startswith("driver."):
            if ORDER_QUEUE_URL:
                targets.append(ORDER_QUEUE_URL)
            if NOTIFICATION_QUEUE_URL:
                targets.append(NOTIFICATION_QUEUE_URL)

        # Order or payment events → Payment queue
        if event_type.startswith("order.") or event_type.startswith("payment."):
            if PAYMENT_QUEUE_URL:
                targets.append(PAYMENT_QUEUE_URL)

        # Send to SQS
        for queue in targets:
            try:
                await sqs.send_message(QueueUrl=queue, MessageBody=json.dumps(body))
                sent = True
                logger.info(f"[SQS] Event '{event_type}' sent to {queue}")
            except Exception as e:
                logger.warning(f"[SQS ERROR] Failed to send '{event_type}' to {queue}: {e}")

        # Push to EventBridge if configured
        if EVENT_BUS:
            try:
                await evb.put_events(Entries=[{
                    "Source": "driver-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(data_with_id),
                    "EventBusName": EVENT_BUS,
                }])
                logger.info(f"[EventBridge] Event '{event_type}' sent to {EVENT_BUS}")
            except Exception:
                logger.exception(f"[EventBridge ERROR] Failed to send '{event_type}'")

    return sent
