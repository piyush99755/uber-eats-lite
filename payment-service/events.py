import os
import json
import boto3
import asyncio
from dotenv import load_dotenv

load_dotenv()  # Load .env variables

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")

if USE_AWS:
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    eventbridge = boto3.client("events", region_name=os.getenv("AWS_REGION"))
    QUEUE_URL = os.getenv("PAYMENT_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")


async def publish_event(event_type: str, payload: dict):
    """
    Publish an event (PaymentProcessed) to SQS + EventBridge or print locally.
    """
    if USE_AWS:
        # Send to SQS
        await asyncio.to_thread(
            sqs.send_message,
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payload)
        )
        # Send to EventBridge
        await asyncio.to_thread(
            eventbridge.put_events,
            Entries=[{
                "Source": "payment-service",
                "DetailType": event_type,
                "Detail": json.dumps(payload),
                "EventBusName": EVENT_BUS
            }]
        )
        print(f"Event {event_type} published to AWS")
    else:
        print(f"{event_type} event:", payload)
