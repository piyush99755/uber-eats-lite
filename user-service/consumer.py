import asyncio
import json
import logging
import os
import aioboto3
from events import log_event_to_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("[User Consumer]")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
QUEUE_URL = os.getenv("USER_SERVICE_QUEUE_URL", "")
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Async SQS client session
# ---------------------------------------------------------------------------
session = aioboto3.Session()


async def handle_message(message: dict):
    event_type = message.get("type")
    data = message.get("data", {})

    # Log to DB
    await log_event_to_db(event_type, data, "user-service")

    # Example logging
    if event_type == "order.created":
        logger.info(f"🧾 order.created for user {data.get('user_name')} — Total: ${data.get('total')}")
    elif event_type == "driver.assigned":
        logger.info(f"🚗 driver.assigned to order {data.get('order_id')} for user {data.get('user_id')}")
    elif event_type == "payment.completed":
        logger.info(f"💰 payment.completed for order {data.get('order_id')} by user {data.get('user_id')}")
    else:
        logger.info(f"ℹ️ {event_type} -> {data}")


async def poll_sqs():
    if not USE_AWS:
        logger.info("[User Consumer] Local mode — skipping AWS polling.")
        while True:
            await asyncio.sleep(10)
        return

    if not QUEUE_URL:
        logger.warning("[User Consumer] No SQS queue configured, skipping polling.")
        return

    logger.info(f"📬 Polling SQS queue: {QUEUE_URL}")

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                for msg in messages:
                    # SQS message body may contain nested "Message"
                    body = json.loads(msg["Body"])
                    payload = json.loads(body["Message"]) if "Message" in body else body
                    await handle_message(payload)

                    await sqs.delete_message(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                logger.error(f"Unexpected error while polling SQS: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_sqs())
