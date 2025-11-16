# order-service/consumer.py
import asyncio
import json
import os
from dotenv import load_dotenv
import aioboto3

from database import database
from models import orders
from events import publish_event, log_event_to_db
from ws_manager import manager  # ✅ WebSocket manager for real-time updates

load_dotenv()

# Environment
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

session = aioboto3.Session()
HTTP_TIMEOUT = 5.0


# ─────────────────────────────────────────────────────────────
# Event Parser (supports local + AWS + SNS → SQS)
# ─────────────────────────────────────────────────────────────
def parse_sqs_message(body: str):
    try:
        outer = json.loads(body)
    except Exception:
        return None, {}, None

    # SNS → SQS nested message
    if isinstance(outer, dict) and "Message" in outer:
        try:
            outer = json.loads(outer["Message"])
        except Exception:
            pass

    # flatten final JSON
    if isinstance(outer, str):
        try:
            outer = json.loads(outer)
        except Exception:
            return None, {}, None

    if not isinstance(outer, dict):
        return None, {}, None

    event_type = (
        outer.get("type")
        or outer.get("event_type")
        or outer.get("detail-type")
    )

    payload = (
        outer.get("data")
        or outer.get("payload")
        or outer.get("detail")
        or {}
    )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    event_id = (
        outer.get("event_id")
        or outer.get("id")
        or payload.get("order_id")
        or payload.get("payment_id")
    )

    return event_type.lower() if event_type else None, payload, event_id


# ─────────────────────────────────────────────────────────────
# PAYMENT HANDLER
# ─────────────────────────────────────────────────────────────
async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        print(f"[Payment Handler] ⚠ Missing order_id: {payload}")
        return

    # Retry if order not yet in DB
    order = None
    for _ in range(3):
        order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
        if order:
            break
        await asyncio.sleep(0.25)

    if not order:
        print(f"[Payment Handler] ❌ Order {order_id} not found")
        return

    if order["payment_status"] == "paid":
        print(f"[Payment Handler] ℹ Already paid ({order_id})")
        return

    # Update DB
    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(payment_status="paid", status="paid")
    )

    print(f"[Payment Handler] ✅ Order {order_id} -> PAID")

    # Broadcast to WebSocket clients
    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })

    # Publish to other services
    await publish_event("order.updated", {
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })


# ─────────────────────────────────────────────────────────────
# DRIVER ASSIGNED HANDLER
# ─────────────────────────────────────────────────────────────
async def handle_driver_assigned(payload: dict):
    order_id = payload.get("order_id")
    driver_id = payload.get("driver_id")
    if not order_id:
        return

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(driver_id=driver_id, status="assigned")
    )

    # Broadcast to WebSocket clients
    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "assigned",
        "driver_id": driver_id
    })

    # Publish to other services
    await publish_event("order.updated", {
        "order_id": order_id,
        "status": "assigned",
        "driver_id": driver_id
    })


# ─────────────────────────────────────────────────────────────
# PAYMENT QUEUE LISTENER
# ─────────────────────────────────────────────────────────────
async def poll_payment_queue():
    if not USE_AWS:
        print("[Order Consumer] Local mode: payment queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Order Consumer] 💳 Listening on {PAYMENT_QUEUE_URL}")
        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=PAYMENT_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                )
                msgs = resp.get("Messages", []) or []

                for msg in msgs:
                    event_type, payload, event_id = parse_sqs_message(msg["Body"])

                    # Dedup
                    if not await log_event_to_db(event_type, payload, "order-service"):
                        await sqs.delete_message(
                            QueueUrl=PAYMENT_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    if event_type == "payment.completed":
                        await handle_payment_completed(payload, event_id)
                    else:
                        print(f"[Order Consumer] ⚠ Unknown event: {event_type}")

                    await sqs.delete_message(
                        QueueUrl=PAYMENT_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
            except Exception as e:
                print(f"[Order Consumer] Payment queue error: {e}")
                await asyncio.sleep(5)


# ─────────────────────────────────────────────────────────────
# DRIVER QUEUE LISTENER
# ─────────────────────────────────────────────────────────────
async def poll_driver_queue():
    if not USE_AWS:
        print("[Order Consumer] Local mode: driver queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Order Consumer] 🚗 Listening on {DRIVER_QUEUE_URL}")
        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=DRIVER_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                )
                msgs = resp.get("Messages", []) or []

                for msg in msgs:
                    event_type, payload, event_id = parse_sqs_message(msg["Body"])

                    if not await log_event_to_db(event_type, payload, "order-service"):
                        await sqs.delete_message(
                            QueueUrl=DRIVER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    if event_type in ("driver.assigned", "driver_assigned"):
                        await handle_driver_assigned(payload)
                    else:
                        print(f"[Order Consumer] ⚠ Unknown driver event: {event_type}")

                    await sqs.delete_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
            except Exception as e:
                print(f"[Order Consumer] Driver queue error: {e}")
                await asyncio.sleep(5)


# ─────────────────────────────────────────────────────────────
# RUN BOTH QUEUES
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def main():
        await asyncio.gather(
            poll_payment_queue(),
            poll_driver_queue(),
        )

    asyncio.run(main())
