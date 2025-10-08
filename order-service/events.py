import os
import boto3
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

# Check if running in AWS or local mode
USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    # Create AWS clients
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    eventbridge = boto3.client("events", region_name=os.getenv("AWS_REGION"))

    # Required env vars
    QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")


async def publish_event(event_type: str, payload: dict):
    """
    Publish an event to AWS (SQS + EventBridge) or print locally.
    :param event_type: The event type (e.g., 'order.created').
    :param payload: The event payload dictionary.
    """
    if USE_AWS:
        try:
            # Send message to SQS
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(payload)
            )
            
             # Send same event to driver-service queue
            sqs.send_message(
                QueueUrl=DRIVER_QUEUE_URL,
                MessageBody=json.dumps({"type": event_type, "data": payload})
            )


            # Send event to EventBridge
            eventbridge.put_events(
                Entries=[{
                    "Source": "order-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(payload),
                    "EventBusName": EVENT_BUS
                }]
            )
            print(f"Event published to AWS: {event_type}")
        except Exception as e:
            print(f"Failed to publish event: {e}")
    else:
        print(f"{event_type} event:", payload)
