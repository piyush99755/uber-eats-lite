# --- payment-service/consumer.py ---
import os
import json
import asyncio
from uuid import uuid4
from dotenv import load_dotenv
import aioboto3
import stripe
from sqlalchemy import select, update, insert
from database import database
from models import payments
from events import publish_event

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
#USE_STRIPE = os.getenv("USE_STRIPE", "False").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Incoming orders
ORDER_CREATED_QUEUE_URL = os.getenv("ORDER_CREATED_QUEUE_URL")
# Outgoing payments for order-service
ORDER_SERVICE_PAYMENT_QUEUE = os.getenv("PAYMENT_QUEUE_URL")

STRIPE_MODE = os.getenv("STRIPE_MODE", "local").lower()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
USE_STRIPE = STRIPE_MODE == "stripe" and bool(STRIPE_SECRET_KEY)

if USE_STRIPE:
    stripe.api_key = STRIPE_SECRET_KEY
    print("[PAYMENT] 💳 Stripe mode enabled")
else:
    print("[PAYMENT] 🧪 Local (non-Stripe) mode active")
session = aioboto3.Session()
sqs_kwargs = {"region_name": AWS_REGION}

# ─────────────────────────────────────────────────────────────
# Process a single payment
# ─────────────────────────────────────────────────────────────
async def process_order_payment(order_event: dict):
    order_id = order_event.get("id")
    user_id = order_event.get("user_id")
    amount = float(order_event.get("total", 0))

    if not order_id:
        print("[PAYMENT] ⚠️ Missing order_id — skipping")
        return

    # Check if payment exists
    existing = await database.fetch_one(
        select(payments).where(payments.c.order_id == order_id)
    )

    payment_id = str(uuid4())
    status = "pending"

    print(f"[PAYMENT] 🔄 Processing payment for Order {order_id} (${amount})")

    try:
        # Stripe payment
        if USE_STRIPE:
            charge = stripe.Charge.create(
                amount=int(amount * 100),
                currency="usd",
                description=f"Payment for Order {order_id}",
                source="tok_visa",
            )
            status = "paid" if charge["status"] == "succeeded" else "failed"
        else:
            # Mock local payment
            await asyncio.sleep(1)
            status = "paid"

        # Insert or update payment record
        if existing:
            payment_id = existing["id"]
            await database.execute(
                update(payments)
                .where(payments.c.id == payment_id)
                .values(status=status, amount=amount)
            )
        else:
            await database.execute(
                insert(payments).values(
                    id=payment_id,
                    order_id=order_id,
                    amount=amount,
                    status=status,
                )
            )

        print(f"[PAYMENT] ✅ Payment {status.upper()} for Order {order_id}")

        # Publish to order-service queue
        event_type = "payment.completed" if status == "paid" else "payment.failed"
        await publish_event(
            event_type,
            {
                "payment_id": payment_id,
                "order_id": order_id,
                "user_id": user_id,
                "status": status,
                "amount": amount,
            },
            queue_url=ORDER_SERVICE_PAYMENT_QUEUE
        )

    except Exception as e:
        print(f"[PAYMENT] ❌ Error processing order {order_id}: {e}")
        await publish_event(
            "payment.failed",
            {
                "order_id": order_id,
                "user_id": user_id,
                "error": str(e),
            },
            queue_url=ORDER_SERVICE_PAYMENT_QUEUE
        )

# ─────────────────────────────────────────────────────────────
# Parse SQS message
# ─────────────────────────────────────────────────────────────
def parse_sqs_message(msg_body: str):
    try:
        data = json.loads(msg_body)
    except Exception:
        print("[PAYMENT] ❌ Invalid JSON message")
        return None, None

    if "Message" in data:
        try:
            data = json.loads(data["Message"])
        except Exception:
            pass

    event_type = data.get("type") or data.get("event_type") or data.get("detail-type")
    payload = data.get("data") or data.get("payload") or data.get("detail") or {}

    if not isinstance(payload, dict):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    return event_type, payload

# ─────────────────────────────────────────────────────────────
# Poll SQS for order.created
# ─────────────────────────────────────────────────────────────
async def poll_orders():
    if not USE_AWS:
        print("[PAYMENT] Local mode — skipping SQS poller")
        while True:
            await asyncio.sleep(10)
        return

    print(f"[PAYMENT] 🚀 Listening for order.created events on {ORDER_CREATED_QUEUE_URL}")

    async with session.client("sqs", **sqs_kwargs) as sqs:
        while True:
            try:
                resp = await sqs.receive_message(
                    QueueUrl=ORDER_CREATED_QUEUE_URL,
                    MaxNumberOfMessages=5,
                    WaitTimeSeconds=10,
                )
                messages = resp.get("Messages", [])

                for msg in messages:
                    body = msg["Body"]
                    receipt = msg["ReceiptHandle"]

                    event_type, payload = parse_sqs_message(body)
                    if event_type != "order.created":
                        print(f"[SKIP] Ignoring event: {event_type}")
                        await sqs.delete_message(
                            QueueUrl=ORDER_CREATED_QUEUE_URL,
                            ReceiptHandle=receipt
                        )
                        continue

                    print(f"[PAYMENT] 📩 Received order.created → {payload.get('id')}")
                    await process_order_payment(payload)

                    await sqs.delete_message(
                        QueueUrl=ORDER_CREATED_QUEUE_URL,
                        ReceiptHandle=receipt
                    )
                    print("[PAYMENT] 🗑️ Deleted SQS message")

            except Exception as e:
                print(f"[PAYMENT] ❌ Polling error: {e}")
                await asyncio.sleep(5)

# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(poll_orders())
    except KeyboardInterrupt:
        print("\n[PAYMENT] 🛑 Stopped by user.")
