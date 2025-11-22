# consumer.py
# consumer.py (order-service) — corrected
import asyncio
import json
import os
from dotenv import load_dotenv
import aioboto3
import logging

from database import database
from models import orders
from events import publish_event, log_event_to_db
from ws_manager import manager

load_dotenv()

logger = logging.getLogger("order-service.consumer")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

session = aioboto3.Session()

# -----------------------------------------------------------
# Event Parser
# -----------------------------------------------------------
def parse_sqs_message(body: str):
    """
    Normalize SQS/SNS/EventBridge message shapes to (event_type, payload_dict, event_id).
    """
    try:
        outer = json.loads(body)
    except Exception:
        return None, {}, None

    # SNS wraps with {"Message": "<json-string>"}
    if isinstance(outer, dict) and "Message" in outer:
        try:
            maybe = json.loads(outer["Message"])
            outer = maybe
        except Exception:
            # leave as-is if it's not JSON
            outer = outer

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

    # payload sometimes is a JSON string
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
# PAYMENT HANDLER (fixed)
# -----------------------------------------------------------
async def handle_payment_completed(payload: dict, event_id=None):
    """
    Called when payment.completed arrives.
    Important: convert DB Record -> dict before using .get(...)
    """
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[Payment] ⚠ Missing order_id in payment.completed payload")
        return

    # Wait briefly for DB record to appear (race with order creation)
    order_row = None
    for _ in range(10):
        order_row = await database.fetch_one(orders.select().where(orders.c.id == order_id))
        if order_row:
            break
        await asyncio.sleep(0.2)

    if not order_row:
        logger.error(f"[Payment] ❌ Order {order_id} not found in DB")
        return

    # convert to plain dict so we can safely use .get()
    order = dict(order_row)

    # Update DB if not already paid
    if order.get("payment_status") != "paid":
        await database.execute(
            orders.update()
            .where(orders.c.id == order_id)
            .values(payment_status="paid", status="paid")
        )
        logger.info(f"[Payment] ✅ Order {order_id} marked PAID")

    # Broadcast to local WS clients
    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })

    # Publish events: payment.completed (so driver-service) and order.updated (UI/notifications)
    # ensure event_id is a string
    ev_id = str(event_id or payload.get("event_id") or order_id)
    await publish_event("payment.completed", {
        "event_id": ev_id,
        "order_id": order_id,
        "payment_status": "paid"
    })

    await publish_event("order.updated", {
        "event_id": ev_id,
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
        logger.warning("[DriverAssigned] ⚠ missing fields")
        return

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(driver_id=driver_id, status="assigned")
    )

    logger.info(f"[DriverAssigned] 🚗 Driver {driver_id} → Order {order_id}")

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

    logger.info(f"[DriverPending] ⚠ Order {order_id} pending: {reason}")

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

    logger.info(f"[DriverFailed] ❌ Order {order_id} failed: {reason}")

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
# Generic poller used by main.startup (keeps code DRY)
# -----------------------------------------------------------
async def poll_queue(queue_url: str, handlers: dict, name: str = "queue"):
    """
    Generic SQS poller. 'handlers' maps event_type -> coroutine function.
    If a handler returns or completes, message will be deleted.
    """
    if not USE_AWS:
        logger.info(f"[{name}] Local mode: queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        logger.info(f"[{name}] Listening → {queue_url}")

        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                )
                messages = resp.get("Messages", []) or []

                for msg in messages:
                    event_type, payload, event_id = parse_sqs_message(msg["Body"])

                    # defensive: if no event_type, still delete to avoid tight loop
                    if not event_type:
                        logger.warning(f"[{name}] ⚠ Received message with no event_type, deleting")
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    processed = await log_event_to_db(event_type, payload, "order-service")
                    if not processed:
                        logger.info(f"[{name}] ⏭ Duplicate {event_type} ({event_id}) — deleting message")
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    handler = handlers.get(event_type)
                    try:
                        if handler:
                            # some handlers expect (payload, event_id), others only (payload)
                            if asyncio.iscoroutinefunction(handler):
                                # call accordingly
                                try:
                                    await handler(payload, event_id)
                                except TypeError:
                                    await handler(payload)
                        else:
                            logger.info(f"[{name}] ⚠ No handler for event type: {event_type}")
                    except Exception as e:
                        logger.exception(f"[{name}] Handler error for {event_type}: {e}")

                    # delete SQS message in all cases to avoid reprocessing loops
                    try:
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                    except Exception as e:
                        logger.warning(f"[{name}] Failed to delete message: {e}")

            except Exception as e:
                logger.exception(f"[{name}] Queue error: {e}")
                await asyncio.sleep(5)


# Expose functions for import by main.py
__all__ = [
    "poll_queue",
    "handle_payment_completed",
    "handle_driver_assigned",
    "handle_driver_failed",
    "handle_driver_pending"
]


# If run directly (not necessary in container since main.py schedules pollers)
if __name__ == "__main__":
    async def main():
        await database.connect()
        await asyncio.gather(
            poll_queue(PAYMENT_QUEUE_URL, {"payment.completed": handle_payment_completed}, "payment.queue"),
            poll_queue(DRIVER_QUEUE_URL, {
                "driver.assigned": handle_driver_assigned,
                "driver.pending": handle_driver_pending,
                "driver.failed": handle_driver_failed
            }, "driver.queue")
        )
    asyncio.run(main())
