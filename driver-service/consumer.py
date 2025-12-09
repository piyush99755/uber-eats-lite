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
        logger.info(f"[Driver Consumer] Skipping duplicate order.created {order_id}")
        return

    # Only log; do NOT assign driver yet, payment not guaranteed
    logger.info(f"[Driver Consumer] Order {order_id} received, waiting for payment completion.")

async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    logger.info(f"[Driver Consumer] Received payment.completed for order_id={order_id}, payload={payload}")

    if not await log_event_to_db("payment.completed", payload, "Driver Service"):
        return

    # Only assign driver if payment is paid and none assigned
    if payload.get("status") == "paid":
        existing_order = await database.fetch_one(
            driver_orders.select().where(driver_orders.c.order_id == order_id)
        )
        if not existing_order or not existing_order.get("driver_id"):
            logger.info(f"[Driver Consumer] Assigning driver for order {order_id} based on payment event.")
            await assign_driver_to_order(order_id)
        else:
            logger.info(f"[Driver Consumer] Driver already assigned for order {order_id}. Skipping.")
    else:
        logger.info(f"[Driver Consumer] Payment status not 'paid'. Skipping driver assignment.")

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

async def handle_driver_failed(payload, event_id=None):
    print("[WARN] driver.failed event ignored — handler not implemented")

async def handle_driver_pending(payload, event_id=None):
    print("[WARN] driver.pending event ignored — handler not implemented")

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
    Assigns a driver to an order, fetching the actual username and saving driver name properly.
    """
    now = datetime.utcnow()

    try:
        # 1️⃣ Fetch full order details
        full_order = await fetch_order_details(order_id)
        if not full_order:
            logger.warning(f"[Driver Assignment] Could not fetch order {order_id}")
            await publish_event("driver.failed", {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "order_not_found"
            })
            return False

        # 2️⃣ Extract USER info
        user_id = str(full_order.get("user_id") or "unknown").strip()

        # Fetch username from users table
        user_record = await database.fetch_one(
            "SELECT name FROM users WHERE id = :uid", values={"uid": user_id}
        )
        user_name = user_record["name"] if user_record else "Unknown"

        # 3️⃣ Extract ITEMS safely
        items_raw = full_order.get("items", [])
        items = []
        if isinstance(items_raw, list):
            items = [str(i) for i in items_raw]
        elif isinstance(items_raw, str):
            try:
                parsed = json.loads(items_raw)
                if isinstance(parsed, list):
                    items = [str(i) for i in parsed]
            except:
                items = []

        # 4️⃣ Extract TOTAL safely
        try:
            total = float(full_order.get("total") or full_order.get("total_amount") or full_order.get("amount") or 0)
        except:
            total = 0.0

        # 5️⃣ Choose available driver
        driver = await choose_available_driver()
        if not driver:
            await publish_event("driver.pending", {
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": "no drivers available"
            })
            return False

        driver_id = driver["id"]

        # 🔍 Fetch real driver name from DB
        driver_record = await database.fetch_one(
            "SELECT name FROM drivers WHERE id = :id", {"id": driver_id}
        )
        driver_name = driver_record["name"] if driver_record else "Unknown"

        # 6️⃣ UPSERT driver_orders
        existing = await database.fetch_one(driver_orders.select().where(driver_orders.c.order_id == order_id))
        if existing:
            await database.execute(
                driver_orders.update()
                .where(driver_orders.c.order_id == order_id)
                .values(
                    driver_id=driver_id,
                    driver_name=driver_name,
                    user_id=user_id,
                    user_name=user_name,
                    items=items,
                    total=total,
                    status="assigned",
                    updated_at=now
                )
            )
        else:
            await database.execute(
                driver_orders.insert().values(
                    id=str(uuid.uuid4()),
                    order_id=order_id,
                    driver_id=driver_id,
                    driver_name=driver_name,
                    user_id=user_id,
                    user_name=user_name,
                    items=items,
                    total=total,
                    status="assigned",
                    created_at=now,
                    updated_at=now
                )
            )

        # 6.1️⃣ ALSO UPDATE ORDER-SERVICE ORDERS TABLE
        try:
            async with httpx.AsyncClient() as client:
                await client.put(
                    f"http://order-service:8002/orders/{order_id}/assign-driver",
                    json={
                        "driver_id": driver_id,
                        "driver_name": driver_name,
                        "status": "assigned"
                    }
                )
                logger.info(f"[Driver Assignment] Updated orders table for order {order_id}")
        except Exception as e:
            logger.error(f"[Driver Assignment] Failed to update order-service order: {e}")

        # 7️⃣ Insert into driver_orders_history
        await database.execute(
            driver_orders_history.insert().values(
                id=str(uuid.uuid4()),
                order_id=order_id,
                driver_id=driver_id,
                driver_name=driver_name,
                user_id=user_id,
                user_name=user_name,
                items=items,
                total=total,
                status="assigned",
                created_at=now,
                updated_at=now
            )
        )

        # 8️⃣ Mark driver as busy
        await database.execute(drivers.update().where(drivers.c.id == driver_id).values(status="busy"))

        # 9️⃣ Emit assigned events
        assigned_payload = {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "user_id": user_id,
            "user_name": user_name,
            "items": items,
            "total": total,
            "status": "assigned",
        }

        await publish_event("driver.assigned", assigned_payload)
        await publish_event("order.updated", assigned_payload)

        if broadcast:
            try:
                await broadcast("driver.assigned", assigned_payload)
                await broadcast("order.updated", assigned_payload)
            except:
                logger.exception("[WS BROADCAST] failed")

        logger.info(f"[Driver Assignment] Assigned driver {driver_name} → order {order_id} (user: {user_name})")

        # 🔟 AUTO-DELIVERY TASK
        async def release_driver_later(did: str, oid: str):
            await asyncio.sleep(random.randint(60, 120))
            delivered_at = datetime.utcnow()

            try:
                async with database.transaction():
                    await database.execute(drivers.update().where(drivers.c.id == did).values(status="available"))
                    await database.execute(
                        driver_orders.update()
                        .where(driver_orders.c.order_id == oid)
                        .values(status="delivered", delivered_at=delivered_at)
                    )
                    await database.execute(
                        driver_orders_history.insert().values(
                            id=str(uuid.uuid4()),
                            order_id=oid,
                            driver_id=did,
                            driver_name=driver_name,
                            user_id=user_id,
                            user_name=user_name,
                            items=items,
                            total=total,
                            status="delivered",
                            created_at=delivered_at,
                            updated_at=delivered_at
                        )
                    )

                delivered_payload = {
                    "event_id": str(uuid.uuid4()),
                    "order_id": oid,
                    "driver_id": did,
                    "driver_name": driver_name,
                    "user_id": user_id,
                    "user_name": user_name,
                    "items": items,
                    "total": total,
                    "status": "delivered",
                    "delivered_at": str(delivered_at),
                }

                await publish_event("order.delivered", delivered_payload)
                await publish_event("driver.available", {"driver_id": did})

                if broadcast:
                    try:
                        await broadcast("order.delivered", delivered_payload)
                        await broadcast("driver.available", {"driver_id": did})
                    except:
                        logger.exception("[WS BROADCAST] failed")

            except:
                logger.exception("[Driver] Error during auto-delivery")

        asyncio.create_task(release_driver_later(driver_id, order_id))

        return True

    except Exception as exc:
        logger.exception(f"[Driver Assignment] Failed for {order_id}: {exc}")
        await publish_event("driver.failed", {
            "event_id": str(uuid.uuid4()),
            "order_id": order_id,
            "reason": str(exc)
        })
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
        "driver.failed": handle_driver_failed,
        "driver.pending": handle_driver_pending,
    })

if __name__ == "__main__":
    asyncio.run(start_driver_consumer())
