import os
import boto3
import json

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs")
    eventbridge = boto3.client("events")
    QUEUE_URL = os.getenv("NOTIFICATION_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")

def publish_event(notification_data: dict):
    if USE_AWS:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(notification_data)
        )
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "notification-service",
                    "DetailType": "NotificationSent",
                    "Detail": json.dumps(notification_data),
                    "EventBusName": EVENT_BUS
                }
            ]
        )
    else:
        print("NotificationSent event:", notification_data)
