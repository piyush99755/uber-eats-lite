import os
import boto3
import json

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs")
    eventbridge = boto3.client("events")
    QUEUE_URL = os.getenv("ORDER_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")

def publish_order_placed_event(order_data: dict):
    if USE_AWS:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(order_data)
        )
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "order-service",
                    "DetailType": "OrderPlaced",
                    "Detail": json.dumps(order_data),
                    "EventBusName": EVENT_BUS
                }
            ]
        )
    else:
        print("OrderPlaced event:", order_data)
