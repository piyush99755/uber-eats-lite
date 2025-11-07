import os
import json
import aioboto3
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from database import database
from models import events
from event_handlers import format_event
from trace import get_or_create_trace_id

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NOTIFICATION_QUEUE_URL = os.getenv("NOTIFICATION_QUEUE_URL")
session = aioboto3.Session()

async def log_event_to_db(event_type: str, data: dict, source_service: str = "notification-service", trace_id: str | None = None):
    """Store event in Postgres DB for dashboard and log to console."""
    trace_id = get_or_create_trace_id(data.get("trace_id") or trace_id)
    event_id = str(uuid.uuid4())
    print(f"[EVENTS] 🧩 [{trace_id}] Logging event → {event_type}")

    if not database.is_connected:
        await database.connect()

    frontend_message = format_event(event_type, data)

    query = events.insert().values(
        id=event_id,
        event_type=event_type,
        source_service=source_service,
        occurred_at=datetime.now(timezone.utc),
        payload=data,
        metadata={"env": "local" if not USE_AWS else "aws", "trace_id": trace_id},
        message=frontend_message
    )

    try:
        await database.execute(query)
        print(f"[EVENTS] ✅ [{trace_id}] Logged event → {event_type}")
        print(f"[NOTIFY] {frontend_message}")
    except Exception as e:
        print(f"[EVENTS] ❌ [{trace_id}] Failed to insert event: {e}")

async def publish_event(event_type: str, data: dict, source_service: str = "notification-service", trace_id: str | None = None):
    trace_id = get_or_create_trace_id(data.get("trace_id") or trace_id)
    event_payload = {
        "type": event_type,
        "data": {**data, "trace_id": trace_id},
        "timestamp": datetime.utcnow().isoformat(),
    }

    await log_event_to_db(event_type, data, source_service=source_service, trace_id=trace_id)

    if USE_AWS:
        try:
            async with session.client("sqs", region_name=AWS_REGION) as sqs:
                await sqs.send_message(
                    QueueUrl=NOTIFICATION_QUEUE_URL,
                    MessageBody=json.dumps(event_payload),
                    MessageAttributes={
                        "trace_id": {"DataType": "String", "StringValue": trace_id}
                    }
                )
            print(f"[EVENTS] ✅ [{trace_id}] Published event → {event_type}")
        except Exception as e:
            print(f"[EVENTS] ❌ [{trace_id}] Failed to publish to AWS SQS: {e}")
    else:
        print(f"[EVENTS] 💡 Local event logged:\n{json.dumps(event_payload, indent=2)}")
