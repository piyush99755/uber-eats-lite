# events.py
import os
import json
import aioboto3
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from database import database
from models import events

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
session = aioboto3.Session()


async def log_event_to_db(event_type: str, data: dict, source_service: str = "notification-service"):
    """Store event in Postgres DB for dashboard."""
    event_id = str(uuid.uuid4())
    print(f"[EVENTS] 🧩 Attempting to log event → {event_type}")

    # Ensure DB is connected
    if not database.is_connected:
        print("[EVENTS] ⚠️ Database not connected, connecting now...")
        await database.connect()

    query = events.insert().values(
        id=event_id,
        event_type=event_type,
        source_service=source_service,
        occurred_at=datetime.now(timezone.utc),
        payload=data,
        metadata={"env": "local" if not USE_AWS else "aws"}
    )

    try:
        await database.execute(query)
        print(f"[EVENTS] ✅ Logged event → {event_type}")
    except Exception as e:
        print(f"[EVENTS] ❌ Failed to insert event: {e}")


async def publish_event(event_type: str, data: dict):
    """Publish event to SQS if AWS is enabled; always log to DB."""
    event_payload = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await log_event_to_db(event_type, data)

    if USE_AWS:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MessageBody=json.dumps(event_payload)
                )
            print(f"[EVENTS] ✅ Published event → {event_type}")
        except Exception as e:
            print(f"[EVENTS] ❌ Failed to publish to AWS SQS: {e}")
    else:
        print(f"[EVENTS] 💡 Local event logged:\n{json.dumps(event_payload, indent=2)}")
