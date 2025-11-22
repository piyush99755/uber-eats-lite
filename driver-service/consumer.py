# driver-service/consumer.py
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

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()


async def release_driver_later(driver_id: str, min_minutes=5, max_minutes=7):
    delay = random.randint(min_minutes * 60, max_minutes * 60)
    print(f"[DriverService] ⏳ Driver {driver_id} auto-release scheduled in {delay}s")
    await asyncio.sleep(delay)
    await database.execute(drivers.update().where(drivers.c.id == driver_id).values(status="available"))
    print(f"[DriverService] 🟢 Driver {driver_id} is available again")
    await publish_event("driver.available", {"event_id": str(uuid.uuid4()), "driver_id": driver_id, "reason": "auto-release"})


async def handle_driver_assignment(event_data: dict):
    order_id = event_data.get("order_id")
    user_id = event_data.get("user_id")
    event_id = event_data.get("event_id") or str(uuid.uuid4())

    if not order_id:
        print(f"[DriverService] ❌ Missing order_id in event: {event_data}")
        return

    print(f"\n[DriverService] 🚕 Assigning driver for order {order_id}")

    driver = await choose_available_driver()
    retries = 0
    max_retries = 3

    while not driver and retries < max_retries:
        print(f"[DriverService] ⚠ No drivers, retrying ({retries+1}/{max_retries})...")
        await publish_event("driver.pending", {"event_id": str(uuid.uuid4()), "order_id": order_id, "reason": "no drivers"})
        await asyncio.sleep(5)
        driver = await choose_available_driver()
        retries += 1

    if not driver:
        print(f"[DriverService] ❌ No drivers available after retries for order {order_id}")
        await publish_event("driver.failed", {"event_id": str(uuid.uuid4()), "order_id": order_id, "reason": "no drivers after retries"})
        return

    driver_id = driver["id"]
    print(f"[DriverService] 🟦 Driver {driver_id} assigned to order {order_id}")

    await database.execute(drivers.update().where(drivers.c.id == driver_id).values(status="busy"))
    print(f"[DriverService] 🔵 Driver {driver_id} set BUSY")

    asyncio.create_task(release_driver_later(driver_id))

    await log_event_to_db("driver.assigned", {"order_id": order_id, "driver_id": driver_id, "user_id": user_id, "event_id": event_id}, "driver-service")

    # publish driver.assigned back to order-service (and notification)
    await publish_event("driver.assigned", {"event_id": event_id, "order_id": order_id, "driver_id": driver_id, "user_id": user_id})

    print(f"[DriverService] ✅ Driver assigned for order {order_id}\n")


async def poll_driver_queue():
    print(f"[DriverService] POLLING DRIVER QUEUE: {DRIVER_QUEUE_URL}")
    if not USE_AWS:
        print("[DriverService] LOCAL MODE → queue disabled")
        while True:
            await asyncio.sleep(10)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[DriverService] 📡 Listening on DRIVER_QUEUE ({DRIVER_QUEUE_URL})")
        while True:
            try:
                resp = await sqs.receive_message(QueueUrl=DRIVER_QUEUE_URL, MaxNumberOfMessages=5, WaitTimeSeconds=10)
                messages = resp.get("Messages", []) or []

                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    print(f"[DriverService DEBUG] Raw SQS message: {msg['Body']}")
                    body = json.loads(msg["Body"])
                    # handle SNS wrapping
                    if isinstance(body, dict) and "Message" in body:
                        try:
                            body = json.loads(body["Message"])
                        except Exception:
                            body = body["Message"]

                    event_type = (body.get("event_type") or body.get("type") or "").lower()
                    payload = body.get("data") or body.get("payload") or body

                    print(f"[DriverService] 📥 Received {event_type}")
                    print(f"[DriverService] Payload: {payload}")

                    processed = await log_event_to_db(event_type, payload, "driver-service")
                    if not processed:
                        print("[DriverService] ⏭ Duplicate skipped")
                        await sqs.delete_message(QueueUrl=DRIVER_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    if event_type == "payment.completed":
                        await handle_driver_assignment(payload)
                    else:
                        print(f"[DriverService] ℹ Ignored event: {event_type}")

                    await sqs.delete_message(QueueUrl=DRIVER_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

            except Exception as e:
                print(f"[DriverService] ❌ Queue error: {e}")
                await asyncio.sleep(5)


async def start_consumers():
    print("[DriverService] 🚀 Starting consumers...")
    print(f"[DriverService] USE_AWS = {USE_AWS}")
    print(f"[DriverService] DRIVER_QUEUE_URL = {DRIVER_QUEUE_URL}")
    await database.connect()
    await poll_driver_queue()


if __name__ == "__main__":
    asyncio.run(start_consumers())
