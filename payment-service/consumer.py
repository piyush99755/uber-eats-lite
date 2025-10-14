import os
import json
import asyncio
from uuid import uuid4
from dotenv import load_dotenv
import aioboto3
from database import database
from models import payments
from events import publish_event

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
ORDER_QUEUE_URL = os.getenv("PAYMENT_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Single reusable session
session = aioboto3.Session()


async def process_order_payment(order_event: dict):
    """
    Process payment for an incoming order and emit payment.processed event.
    """
    try:
        payment_id = str(uuid4())
        user_id = order_event["user_id"]
        order_id = order_event["id"]
        amount = order_event.get("total", 0)

        # Save payment in DB
        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount
        )
        await database.execute(query)

        print(f"[PAYMENT] Payment processed for order {order_id} (${amount})")

        # Emit payment.processed event to Notification Service
        await publish_event("payment.processed", {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "status": "paid",
            "amount": amount
        })

    except Exception as e:
        print(f"[ERROR] Failed to process payment: {e}")


async def poll_orders():
    """
    Poll Order Service SQS queue for OrderCreated events and process payments.
    """
    if not USE_AWS:
        print("[PAYMENT] Local mode — skipping SQS polling.")
        while True:
            await asyncio.sleep(10)
        return

    print(f"[PAYMENT] Listening for OrderCreated events from SQS: {ORDER_QUEUE_URL}")

    async with session.client("sqs", region_name=AWS_REGION) as sqs:
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
                        print(f"[PAYMENT DEBUG] Raw message: {body}")

                        # Handle EventBridge-wrapped messages
                        if "type" in body and body["type"].lower() == "order.created":
                            order_event = body["data"]
                        elif "detail-type" in body and body["detail-type"].lower() == "order.created":
                            detail = body["detail"]
                            order_event = json.loads(detail) if isinstance(detail, str) else detail
                        else:
                            order_event = body  # fallback

                        # Process payment
                        await process_order_payment(order_event)

                        # Delete message from SQS after successful processing
                        await sqs.delete_message(
                            QueueUrl=ORDER_QUEUE_URL,
                            ReceiptHandle=msg["ReceiptHandle"]
                        )
                        print(f"[PAYMENT] 🗑️ Deleted processed message for order {order_event.get('id')}")

                    except Exception as e:
                        print(f"[ERROR] Failed to process message: {e}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)
