import os
import json
import aioboto3
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("driver-service")

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

async def publish_event(event_type: str, data: dict):
    if not USE_AWS:
        print(f"[LOCAL EVENT] {event_type}: {data}")
        return

    try:
        async with session.client("sqs", region_name=AWS_REGION) as sqs:
            await sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({"type": event_type, "data": data})
            )
            print(f"[DRIVER] ✅ Sent event: {event_type}")

    except Exception as e:
        print(f"[EVENT WARN] Failed to send {event_type}: {e}")
