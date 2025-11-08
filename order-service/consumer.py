# --- order-service/consumer.py ---
import asyncio
import json
import os
import aioboto3
from dotenv import load_dotenv
from database import database
from events import publish_event, log_event_to_db
from models import orders

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()


# ------------------------
# Helper: Find available driver
# ------------------------
async def find_available_driver():
    import httpx
    async with httpx.AsyncClient() as client:
        res = await client.get("http://driver-service:8004/drivers?status=available")
        drivers = res.json()
        if drivers:
            return drivers[0]["id"]
    return None


# ------------------------
# Assign driver to order
# ------------------------
async def assign_driver(order_id: str, driver_id: str):
    query = orders.update().where(orders.c.id == order_id).values(
        driver_id=driver_id,
        status="assigned"
    )
    await database.execute(query)

    # Log to DB and publish event
    await log_event_to_db("order.updated", {"order_id": order_id, "driver_id": driver_id})
    await publish_event("order.updated", {"order_id": order_id, "driver_id": driver_id})

    print(f"[Order Updated] ✅ Order {order_id} automatically assigned to driver {driver_id}")


# ------------------------
# Handle driver.assigned event
# ------------------------
async def handle_driver_assigned(event_data: dict):
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

    print(f"[Order Updated] ✅ Order {order_id} assigned to driver {driver_id}")

    await log_event_to_db("order.updated", event_data)
    await publish_event("order.updated", {
        "order_id": order_id,
        "driver_id": driver_id
    })


# ------------------------
# Handle payment.completed event
# ------------------------
async def handle_payment_completed(event):
    order_id = event["order_id"]

    # Update order status to "paid"
    query = orders.update().where(orders.c.id == order_id).values(status="paid")
    await database.execute(query)

    # Assign driver automatically only after payment
    driver_id = await find_available_driver()
    if driver_id:
        # Update order with driver assignment
        assign_query = orders.update().where(orders.c.id == order_id).values(
            driver_id=driver_id,
            status="assigned"
        )
        await database.execute(assign_query)

        # Publish event to notify frontend and other services
        await publish_event("driver.assigned", {
            "order_id": order_id,
            "driver_id": driver_id
        })

    # Log event to database
    await log_event_to_db("payment.completed", event)

# ------------------------
# Poll messages from AWS SQS
# ------------------------
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

                    # Idempotency check
                    processed = await log_event_to_db(event_type, data, "order-service")
                    if not processed:
                        print(f"[DUPLICATE] Skipping reprocessing of {event_type} ({data.get('id')})")
                        await sqs.delete_message(
                            QueueUrl=DRIVER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    # Handle events
                    if event_type == "driver.assigned":
                        await handle_driver_assigned(data)
                    elif event_type == "payment.completed":
                        await handle_payment_completed(data)

                    # Delete message from SQS after processing
                    await sqs.delete_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[Order Consumer ERROR] {e}")
                await asyncio.sleep(5)


# ------------------------
# Optional: Run standalone
# ------------------------
if __name__ == "__main__":
    asyncio.run(poll_messages())
