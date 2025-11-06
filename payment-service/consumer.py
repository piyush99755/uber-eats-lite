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
    """Process payment only for new orders."""
    order_id = order_event.get("id")
    user_id = order_event.get("user_id")
    amount = float(order_event.get("total", 0))

    if not order_id or order_id in processed_orders:
        print(f"[SKIP] Order {order_id} already processed or invalid.")
        return

    processed_orders.add(order_id)
    payment_id = str(uuid4())
    status = "pending"

    print(f"[PAYMENT] 🔄 Processing payment for Order {order_id} — Amount: ${amount}")

    # Process via Stripe or simulate locally
    try:
        if USE_STRIPE:
            charge = stripe.Charge.create(
                amount=int(amount * 100),  # convert to cents
                currency="usd",
                description=f"Payment for Order {order_id}",
                source="tok_visa",  # Test token
            )
            status = "paid" if charge["status"] == "succeeded" else "failed"
        else:
            await asyncio.sleep(1)
            status = "paid"

        # Save payment record in DB
        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status=status
        )
        await database.execute(query)

        print(f"[PAYMENT] ✅ Payment {status.upper()} for Order {order_id}")

        # Publish event to Notification Service
        event_type = "payment.processed" if status == "paid" else "payment.failed"
        await publish_event(event_type, {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "amount": amount
        })

    except Exception as e:
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
