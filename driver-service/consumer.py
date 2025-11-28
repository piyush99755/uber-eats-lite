import asyncio
import os
import json
import logging
import random
from datetime import datetime
import aioboto3
import uuid
from database import database
from models import drivers, processed_events, driver_orders, driver_orders_history
from events import publish_event
from metrics import DRIVER_EVENTS_PROCESSED
from sqlalchemy import and_

from assignment import choose_available_driver

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
    query = drivers.select().where(drivers.c.status == "available").order_by(drivers.c.id.asc())
    available = await database.fetch_all(query)
    if not available:
        logger.info("[Driver Assignment] ❌ No available drivers")
        return None
    driver = available[0]
    logger.info(f"[Driver Assignment] Selected driver {driver['id']}")
    return driver


async def assign_driver_to_order(order_id: str):
    """
    Robust UPSERT-based driver assignment:
      - chooses available driver
      - upserts driver_orders
      - ALWAYS writes driver_orders_history
      - marks driver busy
      - publishes order.updated
      - schedules automatic driver release which updates driver_orders to delivered
        and inserts delivered record into driver_orders_history
    """
    now = datetime.utcnow()

    try:
        async with database.transaction():

            # 1) Pick driver
            driver = await choose_available_driver()
            if not driver:
                await publish_event(
                    "driver.pending",
                    data={
                        "event_id": str(uuid.uuid4()),
                        "order_id": order_id,
                        "reason": "no drivers available"
                    }
                )
                logger.info(f"[Driver Assignment] No driver available for order {order_id}")
                return False

            driver_id = driver["id"]

            # 2) Fetch existing order
            existing = await database.fetch_one(
                driver_orders.select().where(driver_orders.c.id == order_id)
            )

            # 3) Determine driver to assign
            driver_to_use = existing["driver_id"] if existing and existing["driver_id"] else driver_id

            # 4) UPSERT driver_orders
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

            # 5) ALWAYS write history
            await database.execute(
                driver_orders_history.insert().values(
                    id=str(uuid.uuid4()),
                    order_id=order_id,
                    driver_id=driver_to_use,
                    status="assigned",
                    created_at=now
                )
            )

            # 6) Mark driver busy
            await database.execute(
                drivers.update()
                .where(drivers.c.id == driver_id)
                .values(status="busy")
            )

            # 7) Publish assignment event
            await publish_event(
                "order.updated",
                data={
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "driver_id": driver_to_use,
                    "status": "assigned"
                }
            )

            DRIVER_EVENTS_PROCESSED.labels(event_type="assigned").inc()

            logger.info(f"[Driver Assignment] ✅ Order {order_id} assigned to driver {driver_to_use}")

            # 8) Schedule automatic driver release (driver becomes available & order delivered)
            async def release_driver_later(driver_id_inner: str, order_id_inner: str):
                delay = random.randint(60, 120)
                await asyncio.sleep(delay)
                try:
                    async with database.transaction():
                        # Mark driver available
                        await database.execute(
                            drivers.update()
                            .where(drivers.c.id == driver_id_inner)
                            .values(status="available")
                        )
                        logger.info(f"[Driver] Driver {driver_id_inner} is now available")

                        # Update driver_orders to delivered
                        await database.execute(
                            driver_orders.update()
                            .where(driver_orders.c.id == order_id_inner)
                            .values(status="delivered", delivered_at=datetime.utcnow())
                        )

                        # Insert delivered record into history
                        await database.execute(
                            driver_orders_history.insert().values(
                                id=str(uuid.uuid4()),
                                order_id=order_id_inner,
                                driver_id=driver_id_inner,
                                status="delivered",
                                created_at=datetime.utcnow()
                            )
                        )

                        # Publish order.delivered event
                        await publish_event(
                            "order.delivered",
                            data={
                                "order_id": order_id_inner,
                                "driver_id": driver_id_inner,
                                "delivered_at": str(datetime.utcnow()),
                                "origin": "driver-service"
                            }
                        )

                        # Emit driver available event
                        await publish_event("driver.available", data={"driver_id": driver_id_inner})

                except Exception:
                    logger.exception("[Driver] Error releasing driver")

            # Schedule the release
            asyncio.create_task(release_driver_later(driver_id, order_id))

            return True

    except Exception as exc:
        logger.exception(f"[Driver Assignment] Failed for order {order_id}: {exc}")
        await publish_event(
            "driver.failed",
            data={
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "reason": str(exc)
            }
        )
        return False




# ------------------------------- EVENT HANDLERS -------------------------------
async def handle_order_created(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        logger.warning("[Driver] Missing order_id in order.created payload")
        return

    success = await log_event_to_db("order.created", payload, "Driver Service")
    if not success:
        return

    if payload.get("payment_status") == "paid" and not payload.get("driver_id"):
        await assign_driver_to_order(order_id)

    logger.info(f"[Driver] Received order.created: {order_id}")


async def handle_payment_completed(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        return

    success = await log_event_to_db("payment.completed", payload, "Driver Service")
    if not success:
        return

    if payload.get("driver_id"):
        return

    await assign_driver_to_order(order_id)


async def handle_order_delivered(payload: dict, event_id=None):
    order_id = payload.get("order_id") or event_id
    if not order_id:
        return

    success = await log_event_to_db("order.delivered", payload, "Driver Service")
    if not success:
        return

    # Update order to delivered
    row = await database.fetch_one(driver_orders.select().where(driver_orders.c.id == order_id))
    if not row or not row["driver_id"]:
        logger.info(f"[Driver] Delivered order {order_id} has no assigned driver")
        return

    await database.execute(
        driver_orders.update()
        .where(driver_orders.c.id == order_id)
        .values(status="delivered", delivered_at=datetime.utcnow())
    )
    logger.info(f"[Driver] Order {order_id} marked as delivered")


# ------------------------------- SQS POLLER -------------------------------
async def poll_queue(queue_url: str, handlers: dict):
    """
    Robust SQS long-polling consumer.
    - Handles empty responses safely
    - Avoids CPU tight looping
    - Logs clearly
    - Runs forever without freezing
    """
    if not USE_AWS:
        logger.warning("[Driver Consumer] AWS disabled, skipping SQS polling")
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        logger.info(f"[Driver Consumer] Listening on SQS queue: {queue_url}")

        while True:
            try:
                # Long polling (10s)
                resp = await sqs.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,      # long poll
                    VisibilityTimeout=30,
                )

                messages = resp.get("Messages", [])

                # 🔥 If no messages returned → sleep briefly to avoid CPU starvation
                if not messages:
                    await asyncio.sleep(1)
                    continue

                # Process each message
                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type")
                        payload = body.get("data", {})
                        event_id = body.get("event_id")

                        logger.info(f"[Driver Consumer] Received event: {event_type} ({event_id})")

                        handler = handlers.get(event_type)
                        if handler:
                            await handler(payload, event_id)
                        else:
                            logger.warning(f"[Driver Consumer] No handler for event type '{event_type}'")

                        # Successfully processed → delete from queue
                        await sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )

                    except Exception as msg_err:
                        logger.exception(f"[Driver Consumer] Error processing message: {msg_err}")
                        # DO NOT DELETE MESSAGE → it will be retried

            except Exception as poll_err:
                logger.exception(f"[Driver Consumer] Polling error: {poll_err}")
                await asyncio.sleep(5)  # Back off and retry




# ------------------------------- ENTRY POINT -------------------------------
async def start_driver_consumer():
    if not DRIVER_QUEUE_URL:
        logger.warning("[Driver Consumer] DRIVER_QUEUE_URL missing, skipping consumer")
        return

    if not database.is_connected:
        await database.connect()

    logger.info("[Driver Consumer] Starting poller...")
    # Directly run the poller (it loops forever)
    await poll_queue(
        DRIVER_QUEUE_URL,
        {
            "order.created": handle_order_created,
            "payment.completed": handle_payment_completed,
            "order.delivered": handle_order_delivered,
        }
    )


if __name__ == "__main__":
    asyncio.run(start_driver_consumer())
