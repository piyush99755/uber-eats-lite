# --- payment-service/consumer.py ---
import os
import json
import asyncio
from uuid import uuid4
from dotenv import load_dotenv
import aioboto3
import stripe
from database import database
from models import payments
from events import publish_event
from sqlalchemy import select

load_dotenv()

# ─── Environment Setup ─────────────────────────────────────────────
USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
USE_STRIPE = os.getenv("USE_STRIPE", "False").lower() == "true"

ORDER_QUEUE_URL = os.getenv("PAYMENT_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# Configure Stripe (if enabled)
if USE_STRIPE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    print("[PAYMENT] 💳 Stripe mode enabled.")
else:
    print("[PAYMENT] 🧪 Local (non-Stripe) mode active.")

# Configure AWS SQS session
session = aioboto3.Session()
sqs_kwargs = {"region_name": AWS_REGION}

# In-memory cache for processed order IDs to prevent duplicate payments
processed_orders = set()


# ─── Core Payment Processor ─────────────────────────────────────────
async def process_order_payment(order_event: dict):
    order_id = order_event.get("id")
    user_id = order_event.get("user_id")
    amount = float(order_event.get("total", 0))

    if not order_id:
        print("[PAYMENT] ⚠️ Missing order ID, skipping.")
        return

    # ✅ Check DB for existing payment (idempotency)
    existing = await database.fetch_one(
        select(payments).where(payments.c.order_id == order_id)
    )
    if existing:
        print(f"[PAYMENT] 🔁 Order {order_id} already processed — skipping duplicate payment.")
        return

    payment_id = str(uuid4())
    status = "pending"
    print(f"[PAYMENT] 🔄 Processing payment for Order {order_id} — Amount: ${amount}")

    try:
        if USE_STRIPE:
            charge = stripe.Charge.create(
                amount=int(amount * 100),
                currency="usd",
                description=f"Payment for Order {order_id}",
                source="tok_visa",
            )
            status = "paid" if charge["status"] == "succeeded" else "failed"
        else:
            await asyncio.sleep(1)
            status = "paid"

        # ✅ Safe insert (if another instance processed, DB constraint will prevent duplicates)
        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status=status
        )
        await database.execute(query)

        print(f"[PAYMENT] ✅ Payment {status.upper()} for Order {order_id}")
        event_type = "payment.processed" if status == "paid" else "payment.failed"
        await publish_event(event_type, {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "amount": amount
        })

    except Exception as e:
        if "uix_order_id" in str(e):
            print(f"[PAYMENT] ⚠️ Duplicate insert ignored for Order {order_id}")
        else:
            print(f"[ERROR] Failed to process payment for Order {order_id}: {e}")
            await publish_event("payment.failed", {
                "order_id": order_id,
                "user_id": user_id,
                "error": str(e)
            })

# ─── Poller (SQS Consumer) ──────────────────────────────────────────
async def poll_orders():
    """Poll SQS for order.created events only."""
    if not USE_AWS:
        print("[PAYMENT] Local mode: skipping SQS polling.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", **sqs_kwargs) as sqs:
        print(f"[PAYMENT] 🚀 Listening for OrderCreated events on {ORDER_QUEUE_URL}")

        while True:
            try:
                response = await sqs.receive_message(
                    QueueUrl=ORDER_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10
                )
                messages = response.get("Messages", [])

                if not messages:
                    await asyncio.sleep(2)
                    continue

                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        event_type = body.get("type") or body.get("detail-type", "")

                        # Only process order.created
                        if event_type.lower() != "order.created":
                            print(f"[SKIP] Ignoring event {event_type}")
                            await sqs.delete_message(
                                QueueUrl=ORDER_QUEUE_URL,
                                ReceiptHandle=msg["ReceiptHandle"]
                            )
                            continue

                        order_event = body.get("data") or body.get("detail") or body
                        if isinstance(order_event, str):
                            order_event = json.loads(order_event)

                        await process_order_payment(order_event)

                        # Delete processed message from queue
                        await sqs.delete_message(
                            QueueUrl=ORDER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        print(f"[PAYMENT] 🗑️ Deleted message for Order {order_event.get('id')}")

                    except Exception as msg_err:
                        print(f"[ERROR] Failed to process message: {msg_err}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)


# ─── Entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(poll_orders())
    except KeyboardInterrupt:
        print("\n[PAYMENT] 🛑 Stopped by user.")
