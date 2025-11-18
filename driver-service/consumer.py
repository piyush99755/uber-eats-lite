import asyncio
import json
import os
import uuid
import random
import aioboto3
from dotenv import load_dotenv

from database import database
from events import publish_event, log_event_to_db
from assignment import choose_available_driver
from models import drivers

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
ORDER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()


# ───────────────────────────────────────────────
# AUTO RELEASE DRIVER (after delivery)
# ───────────────────────────────────────────────
async def release_driver_later(driver_id: str, min_minutes=5, max_minutes=7):
    delay = random.randint(min_minutes * 60, max_minutes * 60)
    print(f"[DriverService] ⏳ Driver {driver_id} will be released in {delay}s")

    await asyncio.sleep(delay)

    await database.execute(
        drivers.update()
            .where(drivers.c.id == driver_id)
            .values(status="available")
    )

    print(f"[DriverService] 🟢 Driver {driver_id} is AVAILABLE again")

    await publish_event(
        "driver.available",
        {
            "event_id": str(uuid.uuid4()),
            "driver_id": driver_id,
            "reason": "auto-release"
        }
    )


# ───────────────────────────────────────────────
# MAIN DRIVER ASSIGNMENT LOGIC
# ───────────────────────────────────────────────
async def handle_driver_assignment(event_data: dict, max_retries: int = 3, retry_delay: int = 5):
    order_id = event_data.get("order_id")
    user_id = event_data.get("user_id")

    print(f"\n[DriverService] 🚕 Assigning driver for order {order_id}")

    # Ignore unpaid orders
    if event_data.get("status", "").lower() != "paid":
        print(f"[DriverService] ❌ Order {order_id} not paid — skipping")
        return

    retries = 0
    driver = await choose_available_driver()

    while not driver and retries < max_retries:
        print(f"[DriverService] ⚠ No drivers for {order_id}, retrying...")

        await publish_event(
            "driver.pending",
            {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "no drivers available"
            }
        )

        await asyncio.sleep(retry_delay)
        driver = await choose_available_driver()
        retries += 1

    if not driver:
        print(f"[DriverService] ❌ Final fail: no drivers for {order_id}")
        await publish_event(
            "driver.failed",
            {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "no drivers after retries"
            }
        )
        return

    driver_id = driver["id"]
    print(f"[DriverService] 🟦 Driver {driver_id} assigned to order {order_id}")

    await database.execute(
        drivers.update()
            .where(drivers.c.id == driver_id)
            .values(status="busy")
    )

    print(f"[DriverService] 🔵 Driver {driver_id} marked BUSY")

    asyncio.create_task(release_driver_later(driver_id))

    await log_event_to_db(
        "driver.assigned",
        {"order_id": order_id, "driver_id": driver_id},
        "driver-service"
    )

    await publish_event(
        "driver.assigned",
        {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "driver_id": driver_id,
            "user_id": user_id
        }
    )

    print(f"[DriverService] ✅ Done assigning driver for {order_id}\n")


# ───────────────────────────────────────────────
# SQS POLLING
# ───────────────────────────────────────────────
async def poll_queue(queue_url: str, label: str):
    if not USE_AWS:
        print(f"[DriverService] LOCAL MODE → skipping queue {label}")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[DriverService] 📡 Listening on {label}")

        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                for msg in messages:
                    raw = json.loads(msg["Body"])

                    # SNS wrapper?
                    if "Message" in raw:
                        raw = json.loads(raw["Message"])

                    event_type = raw.get("event_type") or raw.get("type")
                    data = raw.get("data") or raw.get("payload") or raw

                    print(f"\n[DriverService] 📥 Received {event_type}")
                    print(f"[DriverService] 🔍 {data}")

                    processed = await log_event_to_db(event_type, data, "driver-service")
                    if not processed:
                        print(f"[DriverService] ⏭ Duplicate skipped")
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    if event_type in ("order.updated", "payment.completed"):
                        await handle_driver_assignment(data)
                    elif event_type.startswith("driver."):
                        print("[DriverService] 📘 Driver event acknowledged")
                    else:
                        print(f"[DriverService] ⚠ Unknown event: {event_type}")

                    await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])

            except Exception as e:
                print(f"[DriverService] ❌ Queue error on {label}: {e}")
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
