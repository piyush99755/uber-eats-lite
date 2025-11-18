# driver-service/events.py
import os
import json
import aioboto3
import logging
from datetime import datetime
from dotenv import load_dotenv
from database import database
from models import processed_events

load_dotenv()

logger = logging.getLogger("driver-service")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

ORDER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()

# Global WebSocket broadcast registry (inject this from your WS server)
websocket_clients = set()

async def register_ws_client(ws):
    """Add WebSocket client to broadcast set."""
    websocket_clients.add(ws)

async def unregister_ws_client(ws):
    """Remove WebSocket client from broadcast set."""
    websocket_clients.discard(ws)

async def broadcast_ws_event(event_type: str, data: dict):
    """Send an event to all connected WebSocket clients."""
    message = json.dumps({
        "event_type": event_type,
        "payload": data,
        "timestamp": datetime.utcnow().isoformat(),
    })
    to_remove = set()
    for ws in websocket_clients:
        try:
            await ws.send(message)
        except Exception as e:
            logger.warning(f"[WS BROADCAST] Failed to send to a client: {e}")
            to_remove.add(ws)
    # Clean up disconnected clients
    for ws in to_remove:
        websocket_clients.discard(ws)

async def publish_event(event_type: str, data: dict, broadcast_ws: bool = True):
    """
    Publish an event to AWS SQS/EventBridge.
    Optionally broadcast to WebSocket clients.
    """
    event_time = datetime.utcnow().isoformat()
    message_body = {
        "type": event_type,
        "data": data,
        "source": "driver-service",
        "timestamp": event_time,
    }

    # Broadcast over WS first (so local dev can see immediately)
    if broadcast_ws:
        await broadcast_ws_event(event_type, data)

    # Local testing without AWS
    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {json.dumps(data, indent=2)}")
        return

    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            # Send event to queues
            for queue_name, queue_url in [
                ("Order Service", ORDER_QUEUE_URL),
                ("Notification Service", NOTIFICATION_QUEUE_URL),
                ("Payment Service", PAYMENT_QUEUE_URL),
            ]:
                if not queue_url:
                    continue
                try:
                    await sqs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(message_body)
                    )
                    logger.info(f"[SENT → {queue_name}] {event_type}")
                except Exception as e:
                    logger.warning(f"[FAILED → {queue_name}] {e}")

            # EventBridge publish
            if EVENT_BUS:
                try:
                    await eventbridge.put_events(
                        Entries=[{
                            "Source": "driver-service",
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
    Logs an event to the processed_events table for idempotency.
    Returns True if it's a new event; False if already processed.
    """
    event_id = data.get("id") or data.get("event_id")
    if not event_id:
        # If no id, still log for visibility but skip dedup logic
        logger.warning(f"[WARN] Event missing ID → {event_type}")
        return True

    # Check if event_id already exists
    query_check = processed_events.select().where(processed_events.c.event_id == event_id)
    existing = await database.fetch_one(query_check)
    if existing:
        logger.info(f"[SKIP] Duplicate event detected ({event_id}) in {source_service}")
        return False

    # Log new event
    query_insert = processed_events.insert().values(
        event_id=event_id,
        event_type=event_type,
        source_service=source_service,
        processed_at=datetime.utcnow(),
    )
    await database.execute(query_insert)
    logger.info(f"[LOGGED] {event_type} ({event_id}) from {source_service}")
    return True
