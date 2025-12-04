# consumer.py (order-service)
import asyncio
import json
import os
from dotenv import load_dotenv
import aioboto3
import logging
from datetime import datetime
from events import publish_event

from database import database
from models import orders
from events import publish_order_created_event, log_event_to_db
from ws_manager import manager

load_dotenv()

logger = logging.getLogger("order-service.consumer")
logger.setLevel(logging.INFO)

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

session = aioboto3.Session()


# -------------------------------
# Event Parser
# -------------------------------
def parse_sqs_message(body: str):
    """
    Normalize SQS/SNS/EventBridge message to (event_type, payload_dict, event_id)
    """
    try:
        msg = json.loads(body)
    except Exception:
        return None, {}, None

    if isinstance(msg, dict) and "Message" in msg:
        try:
            msg = json.loads(msg["Message"])
        except Exception:
            pass

    if isinstance(msg, str):
        try:
            msg = json.loads(msg)
        except Exception:
            return None, {}, None

    event_type = (
        msg.get("type") or msg.get("event_type") or msg.get("detail-type") or msg.get("event")
    )
    payload = msg.get("data") or msg.get("payload") or msg.get("detail") or msg
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    event_id = msg.get("event_id") or msg.get("id") or payload.get("event_id") or payload.get("order_id")
    return (event_type.lower() if isinstance(event_type, str) else None, payload if isinstance(payload, dict) else {}, str(event_id))


# -------------------------------
# Payment Completed Handler
# -------------------------------
async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[Payment] ⚠ Missing order_id in payload")
        return

    # Ensure order exists in DB (race condition)
    order_row = None
    for _ in range(10):
        order_row = await database.fetch_one(orders.select().where(orders.c.id == order_id))
        if order_row:
            break
        await asyncio.sleep(0.2)

    if not order_row:
        logger.error(f"[Payment] ❌ Order {order_id} not found in DB")
        return

    order = dict(order_row)

    if order.get("payment_status") != "paid":
        await database.execute(
            orders.update()
            .where(orders.c.id == order_id)
            .values(payment_status="paid", status="paid")
        )
        logger.info(f"[Payment] ✅ Order {order_id} marked PAID")

    # Broadcast to WebSocket clients
    await manager.broadcast({
        "event": "order.updated",
        "order_id": order_id,
        "status": "paid",
        "payment_status": "paid"
    })

    ev_id = str(event_id or payload.get("event_id") or order_id)
    # Emit both payment.completed and order.updated events
    await publish_event("payment.completed", {"event_id": ev_id, "order_id": order_id, "payment_status": "paid"})
    await publish_event("order.updated", {"event_id": ev_id, "order_id": order_id, "status": "paid", "payment_status": "paid"})


# -------------------------------
# Driver Events Handlers
# -------------------------------
async def handle_driver_assigned(payload: dict, event_id=None):
    order_id = payload.get("order_id")
    driver_id = payload.get("driver_id")
    if not order_id or not driver_id:
        logger.warning("[DriverAssigned] ⚠ Missing fields")
        return

    # Accept driver_name and user_name if provided by driver-service payload
    driver_name = payload.get("driver_name")
    user_name = payload.get("user_name")
    items = payload.get("items")
    total = payload.get("total")

    update_vals = {"driver_id": driver_id, "status": "assigned"}
    if driver_name is not None:
        update_vals["driver_name"] = driver_name
    if user_name is not None:
        update_vals["user_name"] = user_name
    if items is not None:
        # ensure DB stores JSON for items (orders table stores JSON already)
        try:
            # if items is list -> store as-is (we store JSON), else if str -> keep str
            update_vals["items"] = json.dumps(items) if not isinstance(items, str) else items
        except:
            pass
    if total is not None:
        update_vals["total"] = float(total)

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(**update_vals)
    )
    logger.info(f"[DriverAssigned] 🚗 Driver {driver_id} → Order {order_id}")

    # Build payload with full fields so frontend gets correct values
    ws_payload = {
        "event": "order.updated",
        "order_id": order_id,
        "status": "assigned",
        "driver_id": driver_id,
        "driver_name": driver_name,
        "user_name": user_name,
        "items": payload.get("items") if payload.get("items") is not None else None,
        "total": payload.get("total") if payload.get("total") is not None else None,
    }

    # Broadcast and publish
    await manager.broadcast(ws_payload)
    await publish_event("order.updated", {"event_id": str(event_id or payload.get("event_id") or order_id), **ws_payload})


async def handle_order_delivered(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[OrderDelivered] ⚠ Missing order_id")
        return

    # read delivered_at from payload if provided, else now
    delivered_at = payload.get("delivered_at")
    try:
        if not delivered_at:
            delivered_at = datetime.utcnow()
        else:
            # payload might be iso string; try to preserve as-is for DB insert
            delivered_at = delivered_at if isinstance(delivered_at, datetime) else datetime.fromisoformat(str(delivered_at))
    except Exception:
        delivered_at = datetime.utcnow()

    # If payload gives driver_name/user_name/items/total include those too
    driver_id = payload.get("driver_id")
    driver_name = payload.get("driver_name")
    user_name = payload.get("user_name")
    items = payload.get("items")
    total = payload.get("total")

    update_vals = {"status": "delivered", "delivered_at": delivered_at}
    if driver_id:
        update_vals["driver_id"] = driver_id
    if driver_name is not None:
        update_vals["driver_name"] = driver_name
    if user_name is not None:
        update_vals["user_name"] = user_name
    if items is not None:
        # ensure we store items as JSON text in DB
        try:
            update_vals["items"] = json.dumps(items) if not isinstance(items, str) else items
        except:
            pass
    if total is not None:
        try:
            update_vals["total"] = float(total)
        except:
            pass

    await database.execute(
        orders.update()
        .where(orders.c.id == order_id)
        .values(**update_vals)
    )

    logger.info(f"[OrderDelivered] 🎉 Order {order_id} marked DELIVERED")

    # Broadcast WS message for frontend (full payload)
    ws_payload = {
        "event": "order.updated",
        "order_id": order_id,
        "status": "delivered",
        "driver_id": driver_id,
        "driver_name": driver_name,
        "user_name": user_name,
        "items": items,
        "total": total,
        "delivered_at": delivered_at.isoformat() if isinstance(delivered_at, datetime) else str(delivered_at),
    }

    await manager.broadcast(ws_payload)

    # Re-publish internal order.updated event
    await publish_event("order.updated", {"event_id": str(event_id or payload.get("event_id") or order_id), **ws_payload})

async def handle_driver_failed(payload, event_id=None):
    payload["type"] = "driver.failed"
    await handle_driver_event(payload, event_id)


async def handle_driver_pending(payload, event_id=None):
    payload["type"] = "driver.pending"
    await handle_driver_event(payload, event_id)

# -------------------------------
# Driver Event Handler (Refactored)
# -------------------------------
async def handle_driver_event(payload: dict, event_id=None):
    """
    Handles any driver-related event (assigned, pending, failed).
    Updates the DB and broadcasts via WebSocket.
    """
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[DriverEvent] ⚠ Missing order_id in payload")
        return

    # Fetch current order
    order_row = await database.fetch_one(orders.select().where(orders.c.id == order_id))
    if not order_row:
        logger.warning(f"[DriverEvent] ⚠ Order {order_id} not found")
        return

    order = dict(order_row)
    event_type = payload.get("type", "driver.assigned").lower()

    update_values = {}
    ws_payload = {"order_id": order_id}

    # Handle specific driver event types
    if event_type == "driver.assigned":
        driver_id = payload.get("driver_id")
        driver_name = payload.get("driver_name")
        if not driver_id:
            logger.warning(f"[DriverAssigned] ⚠ Missing driver_id for order {order_id}")
            return
        update_values = {"driver_id": driver_id, "driver_name": driver_name, "status": "assigned"}
        ws_payload.update({"status": "assigned", "driver_id": driver_id, "driver_name": driver_name})

    elif event_type == "driver.pending":
        reason = payload.get("reason", "no drivers available")
        ws_payload.update({"reason": reason, "status": "pending"})
        logger.info(f"[DriverPending] ⚠ Order {order_id} pending: {reason}")

    elif event_type == "driver.failed":
        reason = payload.get("reason", "driver assignment failed")
        update_values = {"status": "failed"}
        ws_payload.update({"status": "failed", "reason": reason})
        logger.info(f"[DriverFailed] ❌ Order {order_id} failed: {reason}")

    
    # Update DB if needed
    if update_values:
        await database.execute(orders.update().where(orders.c.id == order_id).values(**update_values))
        logger.info(f"[DriverEvent] ✅ Order {order_id} updated in DB with {update_values}")

    # Broadcast WS
    await manager.broadcast({"event": "order.updated" if event_type != "driver.pending" else "driver.pending", **ws_payload})

    # Publish event to other services
    ev_id = str(event_id or payload.get("event_id") or order_id)
    await publish_event(event_type, {"event_id": ev_id, **ws_payload})

# -------------------------------
# Generic SQS Poller
# -------------------------------
async def poll_queue(queue_url: str, handlers: dict, name: str = "queue"):
    if not USE_AWS:
        logger.info(f"[{name}] Local mode: queue disabled")
        while True:
            await asyncio.sleep(3600)

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        logger.info(f"[{name}] Listening → {queue_url}")
        while True:
            try:
                resp = await sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=5, WaitTimeSeconds=10)
                messages = resp.get("Messages", []) or []

                for msg in messages:
                    event_type, payload, event_id = parse_sqs_message(msg["Body"])
                    if not event_type:
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    processed = await log_event_to_db(event_type, payload, "order-service")
                    if not processed:
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                        continue

                    handler = handlers.get(event_type)
                    if handler:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                try:
                                    await handler(payload, event_id)
                                except TypeError:
                                    await handler(payload)
                        except Exception as e:
                            logger.exception(f"[{name}] Handler error for {event_type}: {e}")

                    try:
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                    except Exception as e:
                        logger.warning(f"[{name}] Failed to delete message: {e}")

            except Exception as e:
                logger.exception(f"[{name}] Queue error: {e}")
                await asyncio.sleep(5)


# -------------------------------
# Expose for main.py
# -------------------------------
__all__ = [
    "poll_queue",
    "handle_payment_completed",
    "handle_driver_assigned",
    "handle_driver_failed",
    "handle_driver_pending"
]


# -------------------------------
# Run directly
# -------------------------------
if __name__ == "__main__":
    async def main():
        await database.connect()
        await asyncio.gather(
            poll_queue(PAYMENT_QUEUE_URL, {"payment.completed": handle_payment_completed}, "payment.queue"),
            poll_queue(DRIVER_QUEUE_URL, {
                "driver.assigned": handle_driver_assigned,
                "driver.pending": handle_driver_pending,
                "driver.failed": handle_driver_failed,
                "order.delivered": handle_order_delivered
            }, "driver.queue")
        )
    asyncio.run(main())
