import asyncio
import json
import os
import boto3
from dotenv import load_dotenv
from database import database
from models import orders
from events import publish_event


load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    DRIVER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")  # messages from driver-service
    sqs = boto3.client("sqs")
else:
    print("[Consumer] Running in local mode; events will be simulated.")


# -------------------------------
# Event handler: driver.assigned
# -------------------------------
async def handle_driver_assigned(event_data: dict):
    """
    Update the order with assigned driver when driver.assigned event is received.
    """
    order_id = event_data.get("order_id")
    driver_id = event_data.get("driver_id")

    if not order_id or not driver_id:
        print("[WARN] Missing order_id or driver_id in driver.assigned event")
        return

    query = orders.update().where(orders.c.id == order_id).values(driver_id=driver_id)
    await database.execute(query)

    print(f"[Order Updated] Order {order_id} assigned to driver {driver_id}")


# -------------------------------
# Poll messages from SQS or local simulation
# -------------------------------
async def poll_messages():
    if USE_AWS:
        print("[Consumer] Starting AWS SQS polling for driver.assigned...")
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

                    if event_type == "driver.assigned":
                        await handle_driver_assigned(event_data)

                    # Delete message after processing
                    sqs.delete_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[Consumer Error] {e}")
                await asyncio.sleep(5)
    else:
        print("[Consumer] Local mode: waiting for driver.assigned events...")
        while True:
            await asyncio.sleep(15)
