# driver-service/consumer.py
import asyncio
import os
import json
import logging
import random
import uuid
from datetime import datetime
import httpx
import aioboto3

from database import database
from models import drivers, processed_events, driver_orders, driver_orders_history
from events import publish_event
from metrics import DRIVER_EVENTS_PROCESSED
from assignment import choose_available_driver  # keep your logic

# WS manager is optional
try:
    from ws_manager import broadcast
except Exception:
    broadcast = None

# ------------------------------- CONFIG -------------------------------
logger = logging.getLogger("driver-service.consumer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

USE_AWS = os.getenv("USE_AWS", "True").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")

session = aioboto3.Session()


# ------------------------------- EVENT LOGGING -------------------------------
async def log_event_to_db(event_type: str, payload: dict, source: str) -> bool:
    """
    Logs event_id in processed_events.
    Returns False if duplicated → skip handler.
    """
    event_id = payload.get("event_id") or payload.get("order_id")
    if not event_id:
        logger.warning(f"[Event Logging] Missing event_id/order_id: {payload}")
        return True  # allow processing

    exists = await database.fetch_one(
        processed_events.select().where(processed_events.c.event_id == event_id)
    )
    if exists:
        logger.info(f"[SKIP] Duplicate {event_type} ({event_id})")
        return False

    await database.execute(
        processed_events.insert().values(
            event_id=event_id,
            event_type=event_type,
            source_service=source,
            processed_at=datetime.utcnow()
        )
    )
    return True

# ----------------- EVENT HANDLERS -----------------
async def handle_order_created(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    logger.info(f"[Driver Consumer] Received order.created for order_id={order_id}, payload={payload}")

    # skip duplicates
    if not await log_event_to_db("order.created", payload, "Driver Service"):
        return

    # assign driver if payment already done
    if payload.get("payment_status") == "paid" and not payload.get("driver_id"):
        await assign_driver_to_order(order_id)


async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    logger.info(f"[Driver Consumer] Received payment.completed for order_id={order_id}, payload={payload}")

    if not await log_event_to_db("payment.completed", payload, "Driver Service"):
        return

    # assign driver if none assigned yet
    if not payload.get("driver_id"):
        await assign_driver_to_order(order_id)


async def handle_order_delivered(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    logger.info(f"[Driver Consumer] Received order.delivered for order_id={order_id}, payload={payload}")

    if not await log_event_to_db("order.delivered", payload, "Driver Service"):
        return

    row = await database.fetch_one(driver_orders.select().where(driver_orders.c.id == order_id))
    if row and row["driver_id"]:
        await database.execute(
            driver_orders.update()
            .where(driver_orders.c.id == order_id)
            .values(status="delivered", delivered_at=datetime.utcnow())
        )

# ------------------------------- DRIVER ASSIGNMENT -------------------------------


async def fetch_order_details(order_id: str):
    """Fetch complete order details from order-service."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://order-service:8002/orders/{order_id}")
        if r.status_code != 200:
            return None
        return r.json()


async def assign_driver_to_order(order_id: str) -> bool:
    """
    Pick an available driver, persist assignment, emit driver.assigned + order.updated,
    mark driver busy and schedule auto-release (delivered + driver.available).
    Returns True if assigned, False otherwise.
    """
    now = datetime.utcnow()

    try:
        # ---------------------------------------------------------
        # 0) Fetch full order details from order-service
        # ---------------------------------------------------------
        full_order = await fetch_order_details(order_id)
        if not full_order:
            logger.warning(f"[Driver Assignment] Could not fetch order {order_id} from order-service")

            await publish_event("driver.failed", {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "order_not_found"
            })
            return False

        # ---------------------------------------------------------
        # 1) Extract user safely (fixes User: Unknown bug)
        # ---------------------------------------------------------
        user_id = None
        if "user_id" in full_order:
            user_id = full_order.get("user_id")
        else:
            user_obj = full_order.get("user")
            if isinstance(user_obj, dict):
                user_id = user_obj.get("id")

        # ---------------------------------------------------------
        # 2) Extract total safely (fixes $NaN bug)
        # ---------------------------------------------------------
        total_raw = (
            full_order.get("total") or
            full_order.get("total_amount") or
            full_order.get("amount") or
            0
        )

        try:
            order_total = float(total_raw)
        except:
            order_total = 0.0

        # ---------------------------------------------------------
        # 3) Choose an available driver
        # ---------------------------------------------------------
        driver = await choose_available_driver()
        if not driver:
            logger.info(f"[Driver Assignment] ❌ No available drivers for order {order_id}")

            await publish_event("driver.pending", {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "no drivers available"
            })
            return False

        driver_id = driver["id"]

        # ---------------------------------------------------------
        # 4) UPSERT driver_orders
        # ---------------------------------------------------------
        existing = await database.fetch_one(
            driver_orders.select().where(driver_orders.c.id == order_id)
        )

        driver_to_use = existing["driver_id"] if existing and existing["driver_id"] else driver_id

        if existing:
            await database.execute(
                driver_orders.update()
                .where(driver_orders.c.id == order_id)
                .values(driver_id=driver_to_use, status="assigned", updated_at=now)
            )
        else:
            await database.execute(
                driver_orders.insert().values(
                    id=order_id,
                    driver_id=driver_to_use,
                    status="assigned",
                    created_at=now,
                    updated_at=now
                )
            )

        # ---------------------------------------------------------
        # 5) Insert into history
        # ---------------------------------------------------------
        await database.execute(
            driver_orders_history.insert().values(
                id=str(uuid.uuid4()),
                order_id=order_id,
                driver_id=driver_to_use,
                status="assigned",
                created_at=now
            )
        )

        # ---------------------------------------------------------
        # 6) Mark driver busy
        # ---------------------------------------------------------
        await database.execute(
            drivers.update().where(drivers.c.id == driver_id).values(status="busy")
        )

        # ---------------------------------------------------------
        # 7) Build final payload (now includes correct user + total)
        # ---------------------------------------------------------
        assigned_payload = {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "driver_id": driver_to_use,
            "user_id": user_id,
            "items": full_order.get("items", []),
            "total": order_total,
            "status": "assigned",
        }

        # ---------------------------------------------------------
        # 8) Publish events
        # ---------------------------------------------------------
        await publish_event("driver.assigned", assigned_payload)
        await publish_event("order.updated", assigned_payload)

        DRIVER_EVENTS_PROCESSED.labels(event_type="assigned").inc()

        if broadcast:
            try:
                await broadcast("driver.assigned", assigned_payload)
                await broadcast("order.updated", assigned_payload)
            except Exception as e:
                logger.warning(f"[WS BROADCAST] direct broadcast failed: {e}")

        logger.info(f"[Driver Assignment] Driver {driver_to_use} assigned → order {order_id}")

        # ---------------------------------------------------------
        # 9) Auto-release after delivery simulation
        # ---------------------------------------------------------
        async def release_driver_later(driver_id2: str, order_id2: str):
            await asyncio.sleep(random.randint(60, 120))
            try:
                async with database.transaction():
                    await database.execute(
                        drivers.update().where(drivers.c.id == driver_id2).values(status="available")
                    )

                    await database.execute(
                        driver_orders.update()
                        .where(driver_orders.c.id == order_id2)
                        .values(status="delivered", delivered_at=datetime.utcnow())
                    )

                    await database.execute(
                        driver_orders_history.insert().values(
                            id=str(uuid.uuid4()),
                            order_id=order_id2,
                            driver_id=driver_id2,
                            status="delivered",
                            created_at=datetime.utcnow()
                        )
                    )

                    delivered_payload = {
                        "event_id": str(uuid.uuid4()),
                        "order_id": order_id2,
                        "driver_id": driver_id2,
                        "delivered_at": str(datetime.utcnow()),
                    }

                    await publish_event("order.delivered", delivered_payload)
                    await publish_event("driver.available", {"driver_id": driver_id2})

                    if broadcast:
                        try:
                            await broadcast("order.delivered", delivered_payload)
                            await broadcast("driver.available", {"driver_id": driver_id2})
                        except Exception:
                            logger.exception("[WS BROADCAST] failed")

            except Exception:
                logger.exception("[Driver] Error releasing driver")

        asyncio.create_task(release_driver_later(driver_id, order_id))

        return True

    except Exception as exc:
        logger.exception(f"[Driver Assignment] Failed for {order_id}: {exc}")

        try:
            await publish_event("driver.failed", {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": str(exc)
            })
        except Exception:
            logger.exception("[Driver Assignment] Failed to publish driver.failed")

        return False




# ------------------------------- SQS CONSUMER -------------------------------
async def poll_queue(queue_url: str, handlers: dict):
    if not USE_AWS:
        logger.warning("AWS disabled. Skipping SQS polling.")
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:

        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                    VisibilityTimeout=30,
                )

                msgs = resp.get("Messages", [])
                if not msgs:
                    await asyncio.sleep(1)
                    continue

                for msg in msgs:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type")
                        payload = body.get("data", {})
                        event_id = body.get("event_id")

                        handler = handlers.get(event_type)
                        if handler:
                            await handler(payload, event_id)

                        await sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )

                    except Exception:
                        logger.exception("Error processing SQS message")

            except Exception:
                logger.exception("SQS polling error")
                await asyncio.sleep(5)


# ------------------------------- STARTUP -------------------------------
async def start_driver_consumer():
    if not DRIVER_QUEUE_URL:
        logger.error("DRIVER_QUEUE_URL missing.")
        return

    if not database.is_connected:
        await database.connect()

    await poll_queue(DRIVER_QUEUE_URL, {
        "order.created": handle_order_created,
        "payment.completed": handle_payment_completed,
        "order.delivered": handle_order_delivered,
    })


if __name__ == "__main__":
    asyncio.run(start_driver_consumer())
