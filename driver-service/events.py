import os
import json
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")               # original driver queue
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")  # notification queue
EVENT_BUS = os.getenv("EVENT_BUS_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

async def publish_event(event_type: str, event_data: dict):
    """
    Publish an event to both Driver Queue, Notification Queue, and EventBridge (async).
    """
    if USE_AWS:
        session = aioboto3.Session()
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            async with session.client("events", region_name=AWS_REGION) as eventbridge:

                # Send to Driver Queue
                await sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps({"type": event_type, "data": event_data})
                )
                print(f"[DRIVER] Sent to SQS: {event_type}")

                # Also send to Notification Queue
                await sqs.send_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MessageBody=json.dumps({"type": event_type, "data": event_data})
                )
                print(f"[DRIVER] Sent to Notification Queue: {event_type}")

                # Send to EventBridge
                await eventbridge.put_events(
                    Entries=[{
                        "Source": "driver-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(event_data),
                        "EventBusName": EVENT_BUS
                    }]
                )
                print(f"[DRIVER] Sent to EventBridge: {event_type}")
    else:
        print(f"[Local Event] {event_type}: {json.dumps(event_data)}")
