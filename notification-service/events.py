import os
import json
import boto3
from dotenv import load_dotenv

load_dotenv()  # Load .env variables

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    eventbridge = boto3.client("events", region_name=os.getenv("AWS_REGION"))
    QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")


async def publish_event(event_type: str, payload: dict):
    """
    Publish an event to AWS (SQS + EventBridge) or print locally.
    """
    if USE_AWS:
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "notification-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(payload),
                    "EventBusName": EVENT_BUS
                }
            ]
        )
    else:
        print(f"{event_type} event:", payload)
