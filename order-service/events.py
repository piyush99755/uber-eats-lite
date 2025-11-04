import os
import json
import uuid
import aioboto3
from datetime import datetime
from dotenv import load_dotenv
from database import database
from models import event_logs

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

ORDER_SERVICE_QUEUE = os.getenv("ORDER_SERVICE_QUEUE")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

session = aioboto3.Session()

async def publish_event(event_type: str, payload: dict):
    """
    Publish an event to multiple SQS queues and optionally EventBridge.
    Also logs the event in the DB.
    """
    event_id = str(uuid.uuid4())

    # Log event in database
    try:
        await database.execute(
            event_logs.insert().values(
                id=event_id,
                event_type=event_type,
                payload=payload,
                source="order-service",
                created_at=datetime.utcnow()
            )
        )
        print(f"[EVENT LOGGED] {event_type} ({event_id})")
    except Exception as e:
        print(f"[WARN] Failed to log event: {e}")

    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {payload}")
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs, \
               session.client("events", region_name=AWS_REGION) as eventbridge:

        # Send to other service queues
        targets = {
            "Notification Queue": NOTIFICATION_QUEUE_URL,
            "Driver Queue": DRIVER_QUEUE_URL,
            "Payment Queue": PAYMENT_QUEUE_URL
        }

        for name, queue_url in targets.items():
            if not queue_url:
                print(f"[WARN] {name} URL not set, skipping.")
                continue

            try:
                await sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({
                        "type": event_type,
                        "data": payload
                    })
                )
                print(f"[SQS SENT] {event_type} -> {name}")
            except Exception as e:
                print(f"[ERROR] Failed to send {event_type} to {name}: {e}")

        # Send to EventBridge
        if EVENT_BUS:
            try:
                await eventbridge.put_events(
                    Entries=[{
                        "Source": "order-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(payload),
                        "EventBusName": EVENT_BUS
                    }]
                )
                print(f"[EVENTBRIDGE SENT] {event_type}")
            except Exception as e:
                print(f"[ERROR] Failed to send to EventBridge: {e}")
