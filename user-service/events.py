import os
import json
import aioboto3
import logging
from datetime import datetime
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv()

logger = logging.getLogger("user-service")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Notification service queue (primary consumer)
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

# Initialize aioboto3 session
session = aioboto3.Session()


# ---------------------------------------------------------------------------
# Event Publisher
# ---------------------------------------------------------------------------
async def publish_event(event_type: str, data: dict):
    """
    Publish user-related events (user.created, user.updated, user.deleted)
    to a single channel to avoid duplicates.
    """
    event_time = datetime.utcnow().isoformat()
    message_body = {
        "type": event_type,
        "data": data,
        "source": "user-service",
        "timestamp": event_time,
    }

    # Local development mode (no AWS)
    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {json.dumps(data, indent=2)}")
        return

    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            # ----------------------------
            # Prefer SQS if configured
            # ----------------------------
            if NOTIFICATION_QUEUE_URL:
                try:
                    await sqs.send_message(
                        QueueUrl=NOTIFICATION_QUEUE_URL,
                        MessageBody=json.dumps(message_body)
                    )
                    logger.info(f"[SQS SENT → Notification Service] {event_type}")
                except Exception as e:
                    logger.warning(f"[SQS ERROR → Notification Service] {e}")
                return  # ✅ stop here to avoid EventBridge duplication

            # ----------------------------
            # Fallback to EventBridge if SQS not configured
            # ----------------------------
            if EVENT_BUS:
                try:
                    await eventbridge.put_events(
                        Entries=[{
                            "Source": "user-service",
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


# ---------------------------------------------------------------------------
# Convenience wrappers for specific user events
# ---------------------------------------------------------------------------
async def user_created(user: dict):
    """Emit user.created event."""
    await publish_event("user.created", user)


async def user_updated(user: dict):
    """Emit user.updated event."""
    await publish_event("user.updated", user)


async def user_deleted(user_id: str):
    """Emit user.deleted event."""
    await publish_event("user.deleted", {"id": user_id})
