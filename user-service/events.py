import os
import json
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
QUEUE_URL = os.getenv("USER_SERVICE_QUEUE")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

async def publish_event(event_type: str, data: dict):
    """
    Publish an event to AWS (SQS + EventBridge) or log locally.
    """
    if USE_AWS:
        session = aioboto3.Session()
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            async with session.client("events", region_name=AWS_REGION) as eventbridge:

                # Send to SQS
                await sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps({"type": event_type, "data": data})
                )
                print(f"[USER] Sent to SQS: {event_type}")

                # Send to EventBridge
                await eventbridge.put_events(
                    Entries=[{
                        "Source": "user-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(data),
                        "EventBusName": EVENT_BUS
                    }]
                )
                print(f"[USER] Sent to EventBridge: {event_type}")
    else:
        print(f"[LOCAL EVENT] {event_type}: {data}")
