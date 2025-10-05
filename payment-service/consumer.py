import os
import json
import asyncio
import boto3
from uuid import uuid4
from events import publish_event
from database import database
from models import payments

# AWS SQS
USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
ORDER_QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")

if USE_AWS:
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION"))
else:
    sqs = None


async def process_order_payment(order_event: dict):
    """
    Process payment for an incoming order.
    """
    payment_id = str(uuid4())
    user_id = order_event["user_id"]
    order_id = order_event["id"]
    amount = order_event.get("total", 0)

    # Save payment to DB
    query = payments.insert().values(id=payment_id, order_id=order_id, amount=amount)
    await database.execute(query)

    print(f"Payment processed: order {order_id}, payment {payment_id}, amount ${amount}")

    # Emit PaymentProcessed event
    await publish_event("PaymentProcessed", {
        "payment_id": payment_id,
        "order_id": order_id,
        "user_id": user_id,
        "status": "paid",
        "amount": amount
    })


async def poll_orders():
    """
    Poll Order Service SQS queue for OrderCreated events.
    """
    if not USE_AWS:
        print("Running locally, skipping SQS consumer")
        return

    print("Payment Service listening for OrderCreated events...")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=ORDER_QUEUE_URL,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10
            )
            messages = response.get("Messages", [])

            if messages:
                for msg in messages:
                    body = json.loads(msg["Body"])
                    await process_order_payment(body)

                    # Delete processed message
                    sqs.delete_message(
                        QueueUrl=ORDER_QUEUE_URL,
                        ReceiptHandle=msg["ReceiptHandle"]
                    )
            else:
                await asyncio.sleep(2)

        except Exception as e:
            print(f"Error polling OrderCreated: {e}")
            await asyncio.sleep(5)
