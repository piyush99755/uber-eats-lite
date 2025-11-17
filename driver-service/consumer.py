import asyncio
import json
import os
import aioboto3
from dotenv import load_dotenv

from database import database
from events import publish_event, log_event_to_db
from assignment import choose_available_driver
from models import drivers
import random

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"

ORDER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

async def release_driver_later(driver_id: str, min_minutes=20, max_minutes=25):
    # Pick a random duration in seconds
    delay = random.randint(min_minutes * 60, max_minutes * 60)
    await asyncio.sleep(delay)

    # Set driver back to available
    await database.execute(
        drivers.update()
        .where(drivers.c.id == driver_id)
        .values(status="available")
    )
    print(f"[DriverService] 🔄 Driver {driver_id} is now AVAILABLE again")
# ───────────────────────────────────────────────
# HANDLE DRIVER ASSIGNMENT
# ───────────────────────────────────────────────
# ───────────────────────────────────────────────
# HANDLE DRIVER ASSIGNMENT (with retry & pending)
# ───────────────────────────────────────────────
async def handle_driver_assignment(event_data: dict, max_retries: int = 3, retry_delay: int = 5):
    order_id = event_data["order_id"]
    user_id = event_data.get("user_id")
    print(f"\n[DriverService] 🔎 Attempting driver assignment for order {order_id}")

    # Check if order is PAID
    if event_data.get("status", "").lower() != "paid":
        print(f"[DriverService] 📝 Order {order_id} not paid yet → skipping assignment")
        return

    # Attempt to pick an available driver with retries
    retries = 0
    driver = await choose_available_driver()
    while not driver and retries < max_retries:
        print(f"[DriverService] ⚠ No available drivers for order {order_id}, retrying in {retry_delay}s...")
        await publish_event(
            "driver.pending",
            {"order_id": order_id, "reason": "no drivers available"}
        )
        await asyncio.sleep(retry_delay)
        driver = await choose_available_driver()
        retries += 1

    if not driver:
        print(f"[DriverService] ❌ Still no available drivers after {max_retries} retries for order {order_id}")
        await publish_event(
            "driver.failed",
            {"order_id": order_id, "reason": "no drivers available after retries"}
        )
        return

    driver_id = driver["id"]
    print(f"[DriverService] 👨‍✈️ Selected driver {driver_id} for order {order_id}")

    # Mark driver busy
    await database.execute(
        drivers.update()
        .where(drivers.c.id == driver_id)
        .values(status="busy")
    )
    print(f"[DriverService] 🔄 Updated driver DB → {driver_id} = busy")

    # Schedule automatic release after 20–25 minutes
    asyncio.create_task(release_driver_later(driver_id))

    # Save event for idempotency
    await log_event_to_db(
        "driver.assigned",
        {"order_id": order_id, "driver_id": driver_id},
        "driver-service"
    )

    # Emit event to SQS
    print(f"[DriverService] 📤 Publishing driver.assigned → order {order_id}")
    await publish_event(
        "driver.assigned",
        {
            "order_id": order_id,
            "driver_id": driver_id,
            "user_id": user_id
        }
    )

    print(f"[DriverService] ✅ Driver assignment completed for order {order_id}\n")

# ───────────────────────────────────────────────
# POLL SQS QUEUE
# ───────────────────────────────────────────────
async def poll_queue(queue_url: str, label: str):
    if not USE_AWS:
        print(f"[Driver Consumer] LOCAL MODE (no AWS) → {label} disabled")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Driver Consumer] 📨 Listening on {label}: {queue_url}")

        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                for msg in messages:
                    print(f"\n[DriverService] 📥 Message received from {label}")

                    body = json.loads(msg["Body"])
                    # --- Support both old and new event formats ---
                    event_type = body.get("event_type") or body.get("type")
                    data = body.get("payload") or body.get("data") or {}

                    print(f"[DriverService] 🔎 Event type: {event_type}")
                    print(f"[DriverService] 🔍 Event data: {data}")

                    # Idempotency check
                    processed = await log_event_to_db(event_type, data, "driver-service")
                    if not processed:
                        print(f"[DriverService] ⏭ Skipping duplicate {event_type}")
                        await sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    # Route events → all events go through driver assignment logic
                    if event_type in ("order.created", "order.updated", "payment.completed"):
                        await handle_driver_assignment(data)
                    else:
                        print(f"[DriverService] ⚠ Unknown event: {event_type}")

                    # Delete message from SQS
                    await sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
                    print(f"[DriverService] 🗑 Message deleted from SQS\n")

            except Exception as e:
                print(f"[Driver Consumer ERROR] {label}: {e}")
                await asyncio.sleep(5)


# ───────────────────────────────────────────────
# START CONSUMERS
# ───────────────────────────────────────────────
async def start_consumers():
    print("[DriverService] 🚀 Starting consumers...")
    await database.connect()

    tasks = [
        asyncio.create_task(poll_queue(ORDER_QUEUE_URL, "order.queue")),
        asyncio.create_task(poll_queue(PAYMENT_QUEUE_URL, "payment.queue")),
    ]

    print("[DriverService] 🟢 Consumers started!")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(start_consumers())
