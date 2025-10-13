import os
import json
import aioboto3
from dotenv import load_dotenv
from database import database
from datetime import datetime
import uuid

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")


async def publish_event(event_type: str, payload: dict):
    """
    Publish an event to Notification & Driver SQS queues and EventBridge asynchronously,
    and log to DB.
    """
    event_id = str(uuid.uuid4())

    # Log event to DB
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
        print(f"[EVENT LOGGED] {event_type} -> {event_id}")
    except Exception as e:
        print(f"[WARN] Failed to log event in DB: {e}")

    if USE_AWS:
        session = aioboto3.Session()
        try:
            # Send to Notification Queue
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                if NOTIFICATION_QUEUE_URL:
                    await sqs.send_message(
                        QueueUrl=NOTIFICATION_QUEUE_URL,
                        MessageBody=json.dumps({"type": event_type, "data": payload})
                    )
                    print(f"[EVENT SENT] {event_type} -> {event_id} to Notification Queue")
                
                # Send to Driver Queue
                if DRIVER_QUEUE_URL:
                    await sqs.send_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        MessageBody=json.dumps({"type": event_type, "data": payload})
                    )
                    print(f"[EVENT SENT] {event_type} -> {event_id} to Driver Queue")

            # Send to EventBridge
            if EVENT_BUS:
                async with session.client("events", region_name=AWS_REGION) as eventbridge:
                    await eventbridge.put_events(
                        Entries=[{
                            "Source": "order-service",
                            "DetailType": event_type,
                            "Detail": json.dumps(payload),
                            "EventBusName": EVENT_BUS
                        }]
                    )
                    print(f"[EVENT SENT] {event_type} -> {event_id} to EventBridge")

        except Exception as e:
            print(f"[ERROR] Failed to publish event: {e}")

    else:
        # Local mode fallback
        print(f"[LOCAL EVENT] {event_type}: {payload}")

    return event_id
