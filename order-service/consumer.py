import asyncio
import json
import os
from dotenv import load_dotenv
import aioboto3

from database import database
from models import orders
from events import publish_event, log_event_to_db
from ws_manager import manager

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

session = aioboto3.Session()


# -----------------------------------------------------------
# Event Parser
# -----------------------------------------------------------
def parse_sqs_message(body: str):
    try:
        outer = json.loads(body)
    except Exception:
        return None, {}, None

    if isinstance(outer, dict) and "Message" in outer:
        try:
            outer = json.loads(outer["Message"])
        except Exception:
            pass

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
        or outer.get("event")
    )

    payload = (
        outer.get("data")
        or outer.get("payload")
        or outer.get("detail")
        or outer
    )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    event_id = (
        outer.get("event_id")
        or outer.get("id")
        or payload.get("event_id")
        or payload.get("order_id")
        or payload.get("payment_id")
    )

    return (
        event_type.lower() if isinstance(event_type, str) else None,
        payload if isinstance(payload, dict) else {},
        event_id
    )


# -----------------------------------------------------------
# PAYMENT HANDLER
# -----------------------------------------------------------
async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        print(f"[Payment] ⚠ Missing order_id: {payload}")
        return

    order = None
    for _ in range(10):
        order = await database.fetch_one(
            orders.select().where(orders.c.id == order_id)
        )
        if order:
            break
        await asyncio.sleep(0.2)

    if not order:
        print(f"[Payment] ❌ Order {order_id} not found")
        return

    if order["payment_status"] != "paid":
        await database.execute(
            orders.update()
            .where(orders.c.id == order_id)
            .values(payment_status="paid", status="paid")
        )
        print(f"[Payment] ✅ Order {order_id} marked PAID")

    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })

    await publish_event("order.updated", {
        "event_id": str(event_id) or str(order_id),
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })


# -----------------------------------------------------------
# DRIVER EVENTS
# -----------------------------------------------------------
async def handle_driver_assigned(payload: dict):
    order_id = payload.get("order_id")
    driver_id = payload.get("driver_id")

    if not order_id or not driver_id:
        print("[DriverAssigned] ⚠ missing fields")
        return

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(driver_id=driver_id, status="assigned")
    )

    print(f"[DriverAssigned] 🚗 Driver {driver_id} → Order {order_id}")

    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "assigned",
        "driver_id": driver_id
    })

    await publish_event("order.updated", {
        "event_id": str(payload.get("event_id") or order_id),
        "order_id": order_id,
        "status": "assigned",
        "driver_id": driver_id
    })


async def handle_driver_pending(payload: dict):
    order_id = payload.get("order_id")
    reason = payload.get("reason", "no drivers available")

    print(f"[DriverPending] ⚠ Order {order_id} pending: {reason}")

    await manager.broadcast({
        "event": "driver.pending",
        "order_id": order_id,
        "reason": reason
    })

    await publish_event("driver.pending", {
        "event_id": str(payload.get("event_id") or order_id),
        "order_id": order_id,
        "reason": reason
    })


async def handle_driver_failed(payload: dict):
    order_id = payload.get("order_id")
    reason = payload.get("reason", "driver assignment failed")

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(status="failed")
    )

    print(f"[DriverFailed] ❌ Order {order_id} failed")

    await manager.broadcast({
        "event": "driver.failed",
        "order_id": order_id,
        "reason": reason
    })

    await publish_event("driver.failed", {
        "event_id": str(payload.get("event_id") or order_id),
        "order_id": order_id,
        "reason": reason
    })


# -----------------------------------------------------------
# PAYMENT QUEUE POLLER
# -----------------------------------------------------------
async def poll_payment_queue():
    if not USE_AWS:
        print("[OrderConsumer] Local mode: payment queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[OrderConsumer] 💳 Listening → {PAYMENT_QUEUE_URL}")

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

                    processed = await log_event_to_db(event_type, payload, "order-service")
                    if not processed:
                        await sqs.delete_message(
                            QueueUrl=PAYMENT_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    if event_type == "payment.completed":
                        await handle_payment_completed(payload, event_id)
                    else:
                        print(f"[OrderConsumer] ⚠ Unknown event {event_type}")

                    await sqs.delete_message(
                        QueueUrl=PAYMENT_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[OrderConsumer] Payment queue error: {e}")
                await asyncio.sleep(5)


# -----------------------------------------------------------
# DRIVER QUEUE POLLER
# -----------------------------------------------------------
async def poll_driver_queue():
    if not USE_AWS:
        print("[OrderConsumer] Local mode: driver queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[OrderConsumer] 🚗 Listening → {DRIVER_QUEUE_URL}")

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

                    processed = await log_event_to_db(event_type, payload, "order-service")
                    if not processed:
                        await sqs.delete_message(
                            QueueUrl=DRIVER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        continue

                    if event_type in ("driver.assigned", "driver_assigned"):
                        await handle_driver_assigned(payload)
                    elif event_type == "driver.pending":
                        await handle_driver_pending(payload)
                    elif event_type == "driver.failed":
                        await handle_driver_failed(payload)
                    else:
                        print(f"[OrderConsumer] ⚠ Unknown driver event {event_type}")

                    await sqs.delete_message(
                        QueueUrl=DRIVER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                print(f"[OrderConsumer] Driver queue error: {e}")
                await asyncio.sleep(5)


# -----------------------------------------------------------
# MAIN ENTRY
# -----------------------------------------------------------
if __name__ == "__main__":
    async def main():
        await database.connect()
        await asyncio.gather(
            poll_payment_queue(),
            poll_driver_queue(),
        )

    asyncio.run(main())
