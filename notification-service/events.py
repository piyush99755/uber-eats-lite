import os
import json
import boto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False") == "True"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

if USE_AWS:
    if not QUEUE_URL:
        raise ValueError("NOTIFICATION_QUEUE_URL is not set.")
    if not EVENT_BUS:
        raise ValueError("EVENT_BUS_NAME is not set.")

    sqs = boto3.client("sqs", region_name=AWS_REGION)
    eventbridge = boto3.client("events", region_name=AWS_REGION)
else:
    print("[Local Mode] Notifications will be printed to console.")


async def publish_event(event_type: str, payload: dict):
    """Publish an event to AWS SQS and EventBridge, or print locally."""
    if USE_AWS:
        try:
            # Send to SQS
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({"type": event_type, "data": payload})
            )

            # Send to EventBridge
            eventbridge.put_events(
                Entries=[{
                    "Source": "notification-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(payload),
                    "EventBusName": EVENT_BUS
                }]
            )
            print(f"[EVENT SENT] {event_type}")
        except Exception as e:
            print(f"[ERROR] Failed to publish event {event_type}: {e}")
    else:
        print(f"[Local Event] {event_type}: {payload}")
