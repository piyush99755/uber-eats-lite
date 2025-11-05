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

# ─── Environment Setup ──────────────────────────────────────────────
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

if USE_AWS:
    print(f"[PAYMENT] Listening for OrderCreated events from SQS: {ORDER_QUEUE_URL}")
else:
    print("[PAYMENT] Local mode — skipping SQS polling.")

# ─── Core Payment Processor ─────────────────────────────────────────
async def process_order_payment(order_event: dict):
    """Handle payment processing for an incoming order event."""
    try:
        payment_id = str(uuid4())
        user_id = order_event.get("user_id")
        order_id = order_event.get("id")
        amount = float(order_event.get("total", 0))
        status = "pending"

        print(f"[PAYMENT] 🔄 Processing payment for Order {order_id} — Amount: ${amount}")

        # Process via Stripe or simulate locally
        if USE_STRIPE:
            print(f"[PAYMENT] 💳 Charging Stripe for order {order_id}")
            try:
                charge = stripe.Charge.create(
                    amount=int(amount * 100),  # convert to cents
                    currency="usd",
                    description=f"Payment for Order {order_id}",
                    source="tok_visa",  # Stripe test token
                )
                status = "paid" if charge["status"] == "succeeded" else "failed"
            except Exception as stripe_err:
                print(f"[STRIPE ERROR] {stripe_err}")
                status = "failed"
        else:
            # Simulate instant payment success
            await asyncio.sleep(1)
            status = "paid"

        # Save payment record
        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status=status
        )
        await database.execute(query)

        print(f"[PAYMENT] ✅ Payment {status.upper()} for Order {order_id}")

        # Publish success/failure event
        event_type = "payment.processed" if status == "paid" else "payment.failed"
        await publish_event(event_type, {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "amount": amount
        })

    except Exception as e:
        print(f"[ERROR] Failed to process payment for order {order_event.get('id')}: {e}")
        await publish_event("payment.failed", {
            "order_id": order_event.get("id"),
            "error": str(e)
        })

# ─── Poller (SQS Consumer) ──────────────────────────────────────────
async def poll_orders():
    """Continuously poll SQS for new order.created events."""
    if not USE_AWS:
        print("[PAYMENT] Local mode: skipping SQS polling.")
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", **sqs_kwargs) as sqs:
        print("[PAYMENT] 🚀 SQS polling started...")
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

                        if "type" in body and body["type"].lower() == "order.created":
                            order_event = body["data"]
                        elif "detail-type" in body and body["detail-type"].lower() == "order.created":
                            detail = body["detail"]
                            order_event = json.loads(detail) if isinstance(detail, str) else detail
                        else:
                            order_event = body

                        await process_order_payment(order_event)

                        # Delete processed message from queue
                        await sqs.delete_message(
                            QueueUrl=ORDER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        print(f"[PAYMENT] 🗑️ Deleted processed message for order {order_event.get('id')}")

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
