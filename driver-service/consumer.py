import asyncio
import json
import os
import boto3
from dotenv import load_dotenv
from database import database
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
DRIVER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")  # SQS for order.created events
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Initialize SQS client
sqs = boto3.client("sqs", region_name=AWS_REGION) if USE_AWS else None

# -------------------------------
# Event handler: order.created
# -------------------------------
async def handle_order_created(event_data: dict):
    """
    Assign an available driver to the order.
    """
    from models import drivers  # Only import local table

    query = drivers.select().where(drivers.c.status == "available")
    available_drivers = await database.fetch_all(query)

    if not available_drivers:
        print("[Driver Assignment] No available drivers.")
        return

    driver = available_drivers[0]
    driver_id = driver["id"]
    order_id = event_data["id"]
    user_id = event_data.get("user_id")

    update_query = drivers.update().where(drivers.c.id == driver_id).values(status="busy")
    await database.execute(update_query)

    print(f"[Driver Assigned] Driver {driver_id} assigned to order {order_id}")

    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": driver_id,
        "user_id": user_id
    })

# -------------------------------
# Poll messages from SQS
# -------------------------------
async def poll_messages():
    if not USE_AWS:
        print("[Consumer] AWS SQS disabled; polling skipped.")
        while True:
            await asyncio.sleep(10)
        return

    print(f"[Consumer] Listening for order.created events from {DRIVER_QUEUE_URL}")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=DRIVER_QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=5
            )
            messages = response.get("Messages", [])

            if not messages:
                await asyncio.sleep(2)
                continue

            for msg in messages:
                body = json.loads(msg["Body"])
                event_type = body.get("type")
                event_data = body.get("data", {})

                if event_type == "order.created":
                    await handle_order_created(event_data)

                sqs.delete_message(
                    QueueUrl=DRIVER_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"]
                )
        except Exception as e:
            print(f"[Consumer Error] {e}")
            await asyncio.sleep(5)
