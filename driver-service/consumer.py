import asyncio
import json
import os
import boto3
from dotenv import load_dotenv


from dotenv import load_dotenv

# Load environment variables from .env in current folder
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Check if AWS mode is enabled
USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"

if USE_AWS:
    print("[AWS mode] Starting SQS consumer loop...")
    ORDER_QUEUE_URL = os.getenv("DRIVER_SERVICE_QUEUE")
    sqs = boto3.client("sqs")
else:
    print("Running consumer in local mode; events will be simulated.")


# -------------------------------
# Event handler: order.created
# -------------------------------
async def handle_order_created(event_data):
    """
    Process the 'order.created' event and assign a driver.
    """
    from database import database
    from models import drivers
    from events import publish_event

    # Find an available driver
    query = drivers.select().where(drivers.c.status == "available")
    available_drivers = await database.fetch_all(query)

    if not available_drivers:
        print("No available drivers right now.")
        return

    # Pick the first one
    driver = available_drivers[0]
    driver_id = driver["id"]
    order_id = event_data["id"]

    # Update driver status → busy
    update_query = drivers.update().where(drivers.c.id == driver_id).values(status="busy")
    await database.execute(update_query)

    print(f"Assigned driver {driver_id} to order {order_id}")

    # Publish driver.assigned event
    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": driver_id
    })


# -------------------------------
# Poll messages from SQS
# -------------------------------
async def poll_messages():
    """
    Continuously polls messages from SQS or simulates in local mode.
    """
    if USE_AWS:
        print("[Consumer] Starting AWS SQS polling...")
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

                    if event_type == "order.created":
                        await handle_order_created(event_data)

                    # Delete message after processing
                    sqs.delete_message(
                        QueueUrl=ORDER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[Consumer Error] {e}")
                await asyncio.sleep(5)

    else:
        # Local testing: simulate waiting for events
        while True:
            print("[Local] Waiting for order.created events...")
            await asyncio.sleep(15)


# Run directly if executed as script
if __name__ == "__main__":
    asyncio.run(poll_messages())
