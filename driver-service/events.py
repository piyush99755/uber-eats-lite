import os
import json
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"

QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

async def publish_event(event_type: str, event_data: dict):
    """
    Publish an event to AWS SQS and EventBridge (async) or print locally.
    """
    if USE_AWS:
        session = aioboto3.Session()
        async with session.client("sqs", region_name=AWS_REGION) as sqs, \
                   session.client("events", region_name=AWS_REGION) as eventbridge:

            await sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({"type": event_type, "data": event_data})
            )

            await eventbridge.put_events(
                Entries=[{
                    "Source": "driver-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(event_data),
                    "EventBusName": EVENT_BUS
                }]
            )
    else:
        print(f"[Local Event] {event_type}: {json.dumps(event_data)}")
