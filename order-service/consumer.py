# order-service/consumer.py
import asyncio
import json
import os
import random
from dotenv import load_dotenv

import aioboto3
import httpx

from database import database
from events import publish_event, log_event_to_db
from models import orders

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
PAYMENT_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

session = aioboto3.Session()

HTTP_TIMEOUT = 5.0
DRIVER_SERVICE_URL = os.getenv("DRIVER_SERVICE_URL", "http://driver-service:8004")


# -------------------------------------------------------------------
# Helper: find available driver
# -------------------------------------------------------------------
async def find_available_driver() -> str | None:
    url = f"{DRIVER_SERVICE_URL}/drivers?status=available"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("id")
    except Exception as e:
        print(f"[Driver Lookup Error] Could not fetch available drivers: {e}")
    return None


# -------------------------------------------------------------------
# Helper: update driver status
# -------------------------------------------------------------------
async def update_driver_status(driver_id: str, status: str) -> bool:
    url = f"{DRIVER_SERVICE_URL}/drivers/drivers/{driver_id}/status"
    payload = {"status": status}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.put(url, json=payload)
            if resp.status_code == 404:
                fallback_url = f"{DRIVER_SERVICE_URL}/drivers/drivers/{driver_id}"
                resp = await client.put(fallback_url, json={"status": status})
            resp.raise_for_status()
            return True
    except Exception as e:
        print(f"[Driver Status Error] Failed to set driver {driver_id} -> {status}: {e}")
    return False


# -------------------------------------------------------------------
# Helper: set driver busy then available
# -------------------------------------------------------------------
async def set_driver_busy(driver_id: str) -> None:
    busy_seconds = random.randint(15 * 60, 30 * 60)
    busy_minutes = busy_seconds // 60
    try:
        ok = await update_driver_status(driver_id, "busy")
        if ok:
            print(f"[Driver] {driver_id} set to BUSY for {busy_minutes}m")
            await log_event_to_db("driver.status_changed", {"driver_id": driver_id, "status": "busy"})
            await publish_event("driver.status_changed", {"driver_id": driver_id, "status": "busy"})
        else:
            print(f"[Driver Warning] Could not mark {driver_id} busy")

        await asyncio.sleep(busy_seconds)

        ok2 = await update_driver_status(driver_id, "available")
        if ok2:
            print(f"[Driver] {driver_id} set back to AVAILABLE")
            await log_event_to_db("driver.status_changed", {"driver_id": driver_id, "status": "available"})
            await publish_event("driver.status_changed", {"driver_id": driver_id, "status": "available"})
    except Exception as e:
        print(f"[Driver Busy Task Error] {e}")


# -------------------------------------------------------------------
# Assign driver → order (DB + event)
# -------------------------------------------------------------------
async def assign_driver(order_id: str, driver_id: str) -> None:
    try:
        update_query = (
            orders.update()
            .where(orders.c.id == order_id)
            .values(driver_id=driver_id, status="assigned")
        )
        await database.execute(update_query)

        event_payload = {"order_id": order_id, "driver_id": driver_id}

        await log_event_to_db("driver.assigned", event_payload)
        await publish_event("driver.assigned", event_payload)

        # Also broadcast order.updated for frontend sync
        await log_event_to_db("order.updated", event_payload)
        await publish_event("order.updated", event_payload)

        print(f"[Order] Driver {driver_id} assigned → order {order_id}")

        # background driver busy cycle
        asyncio.create_task(set_driver_busy(driver_id))
    except Exception as e:
        print(f"[Assign Driver Error] {e}")


# -------------------------------------------------------------------
# Handle driver.assigned events from outside
# -------------------------------------------------------------------
async def handle_driver_assigned(event_data: dict) -> None:
    order_id = event_data.get("order_id")
    driver_id = event_data.get("driver_id")
    if not order_id or not driver_id:
        print("[WARN] driver.assigned missing order_id/driver_id")
        return

    try:
        update_query = (
            orders.update()
            .where(orders.c.id == order_id)
            .values(driver_id=driver_id, status="assigned")
        )
        await database.execute(update_query)
        await log_event_to_db("order.updated", event_data)
        await publish_event("order.updated", event_data)
        print(f"[EventHandler] Applied driver.assigned → order {order_id}")
    except Exception as e:
        print(f"[handle_driver_assigned error] {e}")


# -------------------------------------------------------------------
# Handle payment.completed or payment.processed
# -------------------------------------------------------------------
async def handle_payment_completed(event: dict):
    order_id = event.get("order_id")
    if not order_id:
        print("[WARN] payment.completed missing order_id")
        return

    # Retry fetching order if not yet in DB
    for attempt in range(3):
        order = await database.fetch_one(orders.select().where(orders.c.id == order_id))
        if order:
            break
        print(f"[INFO] Order {order_id} not found, retrying...")
        await asyncio.sleep(0.5)
    else:
        print(f"[ERROR] Order {order_id} still not found after retries")
        return

    update_query = (
        orders.update()
        .where(orders.c.id == order_id)
        .values(payment_status="paid", status="paid")
    )
    await database.execute(update_query)
    print(f"[Order] {order_id} marked as PAID")

    await log_event_to_db("payment.completed", event, source_service="order-service")
    await publish_event("payment.completed", {"order_id": order_id})




# -------------------------------------------------------------------
# Poll messages (AWS)
# -------------------------------------------------------------------
async def poll_messages() -> None:
    if not USE_AWS:
        print("[Order Consumer] AWS disabled, local mode active.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Order Consumer] Listening on {DRIVER_QUEUE_URL}")
        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=DRIVER_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])
                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type")
                        data = body.get("data", {}) or {}

                        processed = await log_event_to_db(event_type, data, "order-service")
                        if not processed:
                            print(f"[DUPLICATE] Skipping {event_type}")
                            await sqs.delete_message(QueueUrl=DRIVER_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                            continue

                        if event_type in ("payment.completed", "payment.processed", "payment.paid"):
                            await handle_payment_completed(data)
                        elif event_type == "driver.assigned":
                            await handle_driver_assigned(data)
                        else:
                            print(f"[Order Consumer] Unhandled event: {event_type}")

                        await sqs.delete_message(QueueUrl=DRIVER_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

                    except Exception as inner_exc:
                        print(f"[Message Handling Error] {inner_exc}")
                        try:
                            await sqs.delete_message(QueueUrl=DRIVER_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Order Consumer ERROR] {e}")
                await asyncio.sleep(5)
                
async def poll_payment_messages() -> None:
    """Listen for payment.completed from Payment Service."""
    if not USE_AWS:
        print("[Order Consumer] AWS disabled, local mode active for payment queue.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
        print(f"[Order Consumer] Listening on {PAYMENT_QUEUE_URL} for payments")
        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=PAYMENT_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])
                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type")
                        data = body.get("data", {})

                        processed = await log_event_to_db(event_type, data, "order-service")
                        if not processed:
                            await sqs.delete_message(QueueUrl=PAYMENT_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                            continue

                        if event_type in ("payment.completed", "payment.processed", "payment.paid"):
                            await handle_payment_completed(data)
                        else:
                            print(f"[Payment Consumer] Unhandled event: {event_type}")

                        await sqs.delete_message(QueueUrl=PAYMENT_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

                    except Exception as inner_exc:
                        print(f"[Payment Message Handling Error] {inner_exc}")
                        try:
                            await sqs.delete_message(QueueUrl=PAYMENT_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Payment Consumer ERROR] {e}")
                await asyncio.sleep(5)



if __name__ == "__main__":
    async def main():
        await asyncio.gather(
            poll_messages(),         # listens on driver queue
            poll_payment_messages()  # listens on payment queue
        )
    asyncio.run(main())
