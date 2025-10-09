import os
import boto3
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv
from database import database
from models import event_logs  # Import the table

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
    Also logs the event to the database for observability.
    :param event_type: The event type (e.g., 'order.created').
    :param payload: The event payload dictionary.
    """
    event_id = str(uuid.uuid4())
    event_entry = {
        "id": event_id,
        "event_type": event_type,
        "payload": payload,
        "source": "order-service",
        "created_at": datetime.utcnow()
    }

    # Log event to DB
    try:
        query = event_logs.insert().values(**event_entry)
        await database.execute(query)
        print(f"[EVENT LOGGED] {event_type} -> {event_id}")
    except Exception as e:
        print(f"[WARN] Failed to log event in DB: {e}")

    # Publish event to AWS or print locally
    if USE_AWS:
        try:
            # Send message to order-service SQS
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(payload)
            )

            # Send message to driver-service SQS
            sqs.send_message(
                QueueUrl=DRIVER_QUEUE_URL,
                MessageBody=json.dumps({"type": event_type, "data": payload})
            )

            # Send to EventBridge
            eventbridge.put_events(
                Entries=[{
                    "Source": "order-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(payload),
                    "EventBusName": EVENT_BUS
                }]
            )
            print(f"[EVENT SENT] {event_type} -> {event_id}")
        except Exception as e:
            print(f"[ERROR] Failed to publish event: {e}")
    else:
        print(f"[LOCAL EVENT] {event_type}: {payload}")

    return event_id
