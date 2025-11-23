import asyncio
import os
import json
import logging
from datetime import datetime
import aioboto3
import uuid
from database import database
from models import drivers, processed_events, driver_orders
from events import publish_event
from metrics import DRIVER_EVENTS_PROCESSED, ACTIVE_DRIVERS  
from sqlalchemy import and_
from sqlalchemy.exc import NoResultFound

# ------------------------------- CONFIG -------------------------------
logger = logging.getLogger("driver-service.consumer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)

USE_AWS = os.getenv("USE_AWS", "True").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
session = aioboto3.Session()

# ------------------------------- UTILS -------------------------------
async def log_event_to_db(event_type: str, payload: dict, source_service: str):
    event_id = payload.get("event_id") or payload.get("order_id")
    if not event_id:
        logger.warning(f"No event_id/order_id in payload: {payload}")
        return True

    existing = await database.fetch_one(
        processed_events.select().where(processed_events.c.event_id == event_id)
    )
    if existing:
        logger.info(f"[SKIP] Duplicate {event_type} ({event_id})")
        return False

    await database.execute(
        processed_events.insert().values(
            event_id=event_id,
            event_type=event_type,
            source_service=source_service,
            processed_at=datetime.utcnow(),
        )
    )
    logger.info(f"[LOGGED] {event_type} ({event_id})")
    return True

async def choose_available_driver():
    query = (
        drivers.select()
        .where(drivers.c.status == "available")
        .order_by(drivers.c.id.asc())
    )
    available = await database.fetch_all(query)
    if not available:
        logger.info("[Driver Assignment] ❌ No available drivers")
        return None
    driver = available[0]
    logger.info(f"[Driver Assignment] Selected driver {driver['id']}")
    return driver



async def assign_driver_to_order(order_id: str):
    """
    Atomically assign an available driver to an order.
    If no driver is available, publish `driver.pending`.
    """
    async with database.transaction():  # start transaction
        # 1️⃣ Pick first available driver
        query = drivers.select().where(drivers.c.status == "available").order_by(drivers.c.id.asc())
        available_drivers = await database.fetch_all(query)
        if not available_drivers:
            logger.info("[Driver Assignment] ❌ No available drivers")
            await publish_event(
                "driver.pending",
                data={
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "reason": "no drivers available"
                }
            )
            return False

        driver = available_drivers[0]

        # 2️⃣ Atomically update order only if unassigned
        update_result = await database.execute(
            driver_orders.update()
            .where(
                and_(
                    driver_orders.c.id == order_id,
                    driver_orders.c.driver_id == None  # only if not assigned
                )
            )
            .values(driver_id=driver["id"], status="assigned")
        )

        # 3️⃣ If order was already assigned, abort
        if update_result == 0:
            logger.info(f"[Driver Assignment] ❌ Order {order_id} already assigned")
            return False

        # 4️⃣ Mark driver as busy
        await database.execute(
            drivers.update().where(drivers.c.id == driver["id"]).values(status="busy")
        )

        # 5️⃣ Publish assignment event
        await publish_event(
            "order.updated",
            data={
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "driver_id": driver["id"],
                "status": "assigned"
            }
        )

        DRIVER_EVENTS_PROCESSED.labels(event_type="assigned").inc()
        logger.info(f"[Driver Assignment] ✅ Order {order_id} assigned to driver {driver['id']}")
        return True

# ------------------------------- EVENT HANDLERS -------------------------------
async def handle_order_created(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[Driver] Missing order_id in order.created payload")
        return

    success = await log_event_to_db("order.created", payload, "Driver Service")
    if not success:
        return

    # Optionally, if payment is already paid (rare on create)
    if payload.get("payment_status") == "paid" and not payload.get("driver_id"):
        await assign_driver_to_order(order_id)

    logger.info(f"[Driver] Received order.created: {order_id}")


async def handle_order_updated(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        return

    success = await log_event_to_db("order.updated", payload, "Driver Service")
    if not success:
        return

    if payload.get("payment_status") != "paid" or payload.get("driver_id"):
        return

    await assign_driver_to_order(order_id)

async def handle_payment_completed(payload: dict, event_id=None):
    logger.info(f"[Driver] Handling payment.completed for {payload.get('order_id')}")
    order_id = payload.get("order_id") or event_id
    if not order_id:
        return

    success = await log_event_to_db("payment.completed", payload, "Driver Service")
    if not success:
        return

    if payload.get("driver_id"):
        return

    await assign_driver_to_order(order_id)

# ------------------------------- SQS POLLER -------------------------------
async def poll_queue(queue_url: str, handlers: dict):
    if not USE_AWS:
        logger.warning("[Driver Consumer] AWS disabled, skipping SQS polling")
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        logger.info(f"[Driver Consumer] Listening to {queue_url} ...")
        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                )
                messages = resp.get("Messages", []) or []

                for msg in messages:
                    body = json.loads(msg["Body"])
                    event_type = body.get("type")       # ✅ correct key
                    payload = body.get("data", {})      # ✅ correct key
                    handler = handlers.get(event_type)
                    if handler:
                        await handler(payload, body.get("event_id"))  # ✅ pass event_id

                    # ✅ delete message after successful processing
                    await sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )

            except Exception as e:
                logger.exception(f"SQS poll error: {e}")
                await asyncio.sleep(5)

# ------------------------------- ENTRY POINT -------------------------------
async def start_driver_consumer():
    if not DRIVER_QUEUE_URL:
        logger.warning("[Driver Consumer] DRIVER_QUEUE_URL missing, skipping consumer")
        return

    if not database.is_connected:
        await database.connect()

    logger.info("[Driver Consumer] Starting poller...")
    asyncio.create_task(
        poll_queue(
            DRIVER_QUEUE_URL,
            {
                 "order.created": handle_order_created,
                "order.updated": handle_order_updated,
                "payment.completed": handle_payment_completed,
            }
        )
    )

if __name__ == "__main__":
    asyncio.run(start_driver_consumer())
