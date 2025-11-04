import asyncio
import json
import logging
import os
import boto3
from botocore.exceptions import ClientError

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("[User Consumer]")

# --------------------------------------------------
# AWS Config
# --------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
QUEUE_URL = os.getenv("USER_SERVICE_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/114913232830/user-service-queue")

sqs = boto3.client("sqs", region_name=AWS_REGION)


# --------------------------------------------------
# Message Handler
# --------------------------------------------------
async def handle_message(message: dict):
    """
    Reacts to messages from other services.
    You can expand this as needed to trigger user-related workflows.
    """
    event_type = message.get("event_type")
    data = message.get("data", {})

    if event_type == "order.created":
        logger.info(f"🧾 Received event: order.created for user {data.get('user_name')} — Total: ${data.get('total')}")
        # Optional: e.g., update user stats, send loyalty points, etc.

    elif event_type == "driver.assigned":
        logger.info(f"🚗 Driver assigned to order {data.get('order_id')} for user {data.get('user_id')}")
        # Optional: mark user's order status as 'driver assigned' in DB.

    elif event_type == "payment.completed":
        logger.info(f"💰 Payment completed for order {data.get('order_id')} by user {data.get('user_id')}")
        # Optional: update user purchase history, rewards, etc.

    else:
        logger.warning(f"⚠️ Unknown event type received: {event_type} -> {data}")


# --------------------------------------------------
# Polling Loop
# --------------------------------------------------
async def poll_sqs():
    logger.info(f"📬 Polling SQS queue: {QUEUE_URL}")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10
            )

            messages = response.get("Messages", [])
            for msg in messages:
                body = json.loads(msg["Body"])
                try:
                    # SQS from EventBridge or SNS might wrap the payload
                    payload = json.loads(body.get("Message", "{}")) if "Message" in body else body
                    await handle_message(payload)
                except json.JSONDecodeError:
                    logger.error(f"❌ Failed to parse message body: {body}")

                # Delete message after successful handling
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

        except ClientError as e:
            logger.error(f"AWS ClientError: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await asyncio.sleep(5)


# --------------------------------------------------
# Entry Point
# --------------------------------------------------
if __name__ == "__main__":
    logger.info("[User Consumer] Starting event listener loop...")
    asyncio.run(poll_sqs())
