import asyncio
import json
import os
import aioboto3
from dotenv import load_dotenv
from database import database
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
ORDER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()


async def handle_order_created(event_data: dict):
    from models import drivers

    query = drivers.select().where(drivers.c.status == "available")
    available_drivers = await database.fetch_all(query)

    if not available_drivers:
        print("[Driver Assignment] ❌ No available drivers.")
        return

    driver = available_drivers[0]
    driver_id = driver["id"]
    order_id = event_data["id"]
    user_id = event_data.get("user_id")

    await database.execute(
        drivers.update().where(drivers.c.id == driver_id).values(status="busy")
    )

    print(f"[Driver Assigned] 🚗 Driver {driver_id} → Order {order_id}")

    # ✅ Log to DB
    await log_event_to_db("driver.assigned", {"order_id": order_id, "driver_id": driver_id}, "driver-service")

    await publish_event("driver.assigned", {
        "order_id": order_id,
        "driver_id": driver_id,
        "user_id": user_id
    })


async def poll_messages():
    if not USE_AWS:
        print("[Driver Consumer] Local mode — skipping AWS polling.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Driver Consumer] Polling order events from: {ORDER_QUEUE_URL}")

        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=ORDER_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                for msg in messages:
                    body = json.loads(msg["Body"])
                    event_type = body.get("type")
                    data = body.get("data", {})

                    await log_event_to_db(event_type, data, "driver-service")

                    if event_type == "order.created":
                        await handle_order_created(data)

                    await sqs.delete_message(
                        QueueUrl=ORDER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[Driver Consumer ERROR] {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_messages())
