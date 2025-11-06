import os
import json
import aioboto3
from dotenv import load_dotenv

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

async def publish_event(event_type: str, payload: dict):
    """Publish an event to Notification SQS after DB success."""
    message = {"type": event_type, "data": payload}

    if USE_AWS and NOTIFICATION_QUEUE_URL:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )
        except Exception as e:
            print(f"[ERROR] Failed to send to Notification SQS: {e}")
    else:
        print(f"[LOCAL EVENT] {event_type}: {payload}")
