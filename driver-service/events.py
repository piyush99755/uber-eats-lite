# driver-service/events.py
import os
import json
import aioboto3
import logging
from datetime import datetime
from dotenv import load_dotenv

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

async def publish_event(event_type: str, data: dict):
    """Publish an event to AWS SQS/EventBridge."""
    event_time = datetime.utcnow().isoformat()
    message_body = {
        "type": event_type,
        "data": data,
        "source": "driver-service",
        "timestamp": event_time,
    }

    # Local testing
    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {json.dumps(data, indent=2)}")
        return

    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            # Send event to relevant queues
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

            # Publish to EventBridge (optional)
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
