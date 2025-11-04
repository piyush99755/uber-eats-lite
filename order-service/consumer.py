import asyncio
import json
import os
import aioboto3
from dotenv import load_dotenv
from database import database
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

# -------------------------------
# Event handler: driver.assigned
# -------------------------------
async def handle_driver_assigned(event_data: dict):
    from models import orders

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

    print(f"[Order Updated] ✅ Order {order_id} assigned to driver {driver_id}")

# -------------------------------
# Poll messages from SQS
# -------------------------------
async def poll_messages():
    if not USE_AWS:
        print("[Order Consumer] AWS disabled, skipping poll.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Order Consumer] Listening for driver.assigned events from {DRIVER_QUEUE_URL}")

        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=DRIVER_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                for msg in messages:
                    body = json.loads(msg["Body"])
                    event_type = body.get("type")
                    data = body.get("data", {})

                    if event_type == "driver.assigned":
                        await handle_driver_assigned(data)

                    # Delete message
                    await sqs.delete_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[Order Consumer ERROR] {e}")
                await asyncio.sleep(5)
