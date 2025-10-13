import os
import json
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
QUEUE_URL = os.getenv("PAYMENT_SERVICE_QUEUE")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

async def publish_event(event_type: str, payload: dict):
    """
    Publish an event (PaymentProcessed) to SQS + EventBridge or print locally.
    """
    if USE_AWS:
        session = aioboto3.Session()
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            async with session.client("events", region_name=AWS_REGION) as eventbridge:

                # Send to SQS
                await sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps({"type": event_type, "data": payload})
                )
                print(f"[PAYMENT] Sent to SQS: {event_type}")

                # Send to EventBridge
                await eventbridge.put_events(
                    Entries=[{
                        "Source": "payment-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(payload),
                        "EventBusName": EVENT_BUS
                    }]
                )
                print(f"[PAYMENT] Sent to EventBridge: {event_type}")
    else:
        print(f"[LOCAL EVENT] {event_type}: {payload}")
