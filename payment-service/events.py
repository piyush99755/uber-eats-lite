import os
import json
import boto3
import asyncio

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs")
    eventbridge = boto3.client("events")
    QUEUE_URL = os.getenv("PAYMENT_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")

async def publish_event(payment_data: dict):
    if USE_AWS:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payment_data)
        )
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "payment-service",
                    "DetailType": "PaymentProcessed",
                    "Detail": json.dumps(payment_data),
                    "EventBusName": EVENT_BUS
                }
            ]
        )
    else:
        print("PaymentProcessed event:", payment_data)
