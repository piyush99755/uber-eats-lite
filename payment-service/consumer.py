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

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
ORDER_QUEUE_URL = os.getenv("PAYMENT_SERVICE_QUEUE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Configure aioboto3 session
session = aioboto3.Session()
sqs_kwargs = {"region_name": AWS_REGION}

if USE_AWS:
    print(f"[PAYMENT] Listening for OrderCreated events from SQS: {ORDER_QUEUE_URL}")
else:
    print("[PAYMENT] Local mode — skipping SQS polling.")

async def process_order_payment(order_event: dict):
    try:
        payment_id = str(uuid4())
        user_id = order_event["user_id"]
        order_id = order_event["id"]
        amount = order_event.get("total", 0)

        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount
        )
        await database.execute(query)

        print(f"[PAYMENT] Payment processed for order {order_id} (${amount})")

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
    if not USE_AWS:
        while True:
            await asyncio.sleep(10)
        return

    async with session.client("sqs", **sqs_kwargs) as sqs:
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
                    body = json.loads(msg["Body"])
                    if "type" in body and body["type"].lower() == "order.created":
                        order_event = body["data"]
                    elif "detail-type" in body and body["detail-type"].lower() == "order.created":
                        detail = body["detail"]
                        order_event = json.loads(detail) if isinstance(detail, str) else detail
                    else:
                        order_event = body

                    await process_order_payment(order_event)

                    await sqs.delete_message(
                        QueueUrl=ORDER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
                    print(f"[PAYMENT] 🗑️ Deleted processed message for order {order_event.get('id')}")

            except Exception as e:
                print(f"[ERROR] Polling failed: {e}")
                await asyncio.sleep(5)
