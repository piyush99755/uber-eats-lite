import os
import json
import asyncio
import boto3
from database import database
from models import notifications
from uuid import uuid4
from events import publish_event

ORDER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")
USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs")
else:
    sqs = None


async def process_order_event(order_event: dict):
    """
    Handle incoming order.created event and create a notification.
    """
    notification_id = str(uuid4())
    message = f"Your order {order_event['id']} with items {order_event['items']} has been placed!"

    # Save to DB
    query = notifications.insert().values(
        id=notification_id,
        user_id=order_event["user_id"],
        message=message
    )
    await database.execute(query)

    # Publish notification.created event
    await publish_event("notification.created", {
        "id": notification_id,
        "user_id": order_event["user_id"],
        "message": message
    })

    print(f"Processed order event into notification: {notification_id}")


async def poll_sqs():
    """
    Continuously poll SQS for messages.
    """
    if not USE_AWS:
        print("Running in local mode; skipping SQS consumer")
        return

    while True:
        response = sqs.receive_message(
            QueueUrl=ORDER_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10
        )

        messages = response.get("Messages", [])
        for msg in messages:
            body = json.loads(msg["Body"])
            print("Received order event:", body)

            await process_order_event(body)

            # Delete message after processing
            sqs.delete_message(
                QueueUrl=ORDER_QUEUE_URL,
                ReceiptHandle=msg["ReceiptHandle"]
            )

        await asyncio.sleep(2)  # avoid hot loop
