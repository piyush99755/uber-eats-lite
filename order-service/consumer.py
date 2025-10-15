import asyncio
import json
import os
import boto3
from dotenv import load_dotenv
from database import database
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
ORDER_QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")  # SQS for driver events
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Initialize SQS client
sqs = boto3.client("sqs", region_name=AWS_REGION) if USE_AWS else None

# -------------------------------
# Event handler: driver.assigned
# -------------------------------
async def handle_driver_assigned(event_data: dict):
    """
    Update order status when a driver is assigned.
    """
    from models import orders  # Only import local table

    order_id = event_data.get("order_id")
    driver_id = event_data.get("driver_id")

    if not order_id or not driver_id:
        print("[WARN] Missing order_id or driver_id in driver.assigned event")
        return

    query = orders.update().where(orders.c.id == order_id).values(
        driver_id=driver_id,
        status="assigned"
    )
    await database.execute(query)

    await publish_event("order.updated", {
        "order_id": order_id,
        "driver_id": driver_id
    })

    print(f"[Order Updated] Order {order_id} assigned to driver {driver_id}")

# -------------------------------
# Poll messages from SQS
# -------------------------------
async def poll_messages():
    if not USE_AWS:
        print("[Consumer] AWS SQS disabled; polling skipped.")
        while True:
            await asyncio.sleep(10)
        return

    print(f"[Consumer] Listening for driver.assigned events from {ORDER_QUEUE_URL}")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=ORDER_QUEUE_URL,
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

                if event_type == "driver.assigned":
                    await handle_driver_assigned(event_data)

                sqs.delete_message(
                    QueueUrl=ORDER_QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"]
                )
        except Exception as e:
            print(f"[Consumer Error] {e}")
            await asyncio.sleep(5)
