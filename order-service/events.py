import os
import boto3
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv
from database import database
from models import event_logs  # Event logs table

# -----------------------------
# Load environment variables
# -----------------------------
load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False") == "True"

# SQS Queues
ORDER_SERVICE_QUEUE = os.getenv("ORDER_SERVICE_QUEUE")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL") 
# EventBridge Bus
EVENT_BUS = os.getenv("EVENT_BUS_NAME")

# -----------------------------
# Validate URLs in AWS mode
# -----------------------------
if USE_AWS:
    missing_queues = []
    if not ORDER_SERVICE_QUEUE:
        missing_queues.append("ORDER_SERVICE_QUEUE")
    if not DRIVER_QUEUE_URL:
        missing_queues.append("DRIVER_QUEUE_URL")
    if not NOTIFICATION_QUEUE_URL:
        missing_queues.append("NOTIFICATION_QUEUE_URL")
    if not PAYMENT_QUEUE_URL:
        missing_queues.append("PAYMENT_QUEUE_URL") 
    if not EVENT_BUS:
        missing_queues.append("EVENT_BUS_NAME")

    if missing_queues:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_queues)}")

    # Create AWS clients
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
    eventbridge = boto3.client("events", region_name=os.getenv("AWS_REGION"))
else:
    print("[LOCAL MODE] Running locally, events will be printed only.")

# -----------------------------
# Publish event function
# -----------------------------
async def publish_event(event_type: str, payload: dict):
    """
    Publish an event to Notification, Driver, and Payment SQS queues,
    log to DB, and optionally send to EventBridge.
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

    # Send message to AWS SQS
    if USE_AWS:
        for queue_name, queue_url in [
            ("Notification Queue", NOTIFICATION_QUEUE_URL),
            ("Driver Queue", DRIVER_QUEUE_URL),
            ("Payment Queue", PAYMENT_QUEUE_URL) 
        ]:
            if not queue_url:
                print(f"[WARN] {queue_name} URL not set, skipping...")
                continue
            try:
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({
                        "type": event_type,
                        "data": payload
                    })
                )
                print(f"[EVENT SENT] {event_type} -> {event_id} to {queue_name} ({queue_url})")
            except Exception as e:
                print(f"[ERROR] Failed to send event to {queue_name} ({queue_url}): {e}")

        # Send to EventBridge
        if EVENT_BUS:
            try:
                eventbridge.put_events(
                    Entries=[{
                        "Source": "order-service",
                        "DetailType": event_type,
                        "Detail": json.dumps(payload),
                        "EventBusName": EVENT_BUS
                    }]
                )
                print(f"[EVENT SENT] {event_type} -> {event_id} to EventBridge")
            except Exception as e:
                print(f"[ERROR] Failed to send to EventBridge: {e}")
        else:
            print("[WARN] EVENT_BUS_NAME not set, skipping EventBridge publish.")
    else:
        # Local mode: just print
        print(f"[LOCAL EVENT] {event_type}: {payload}")

    return event_id
