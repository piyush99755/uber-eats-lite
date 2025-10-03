import os
import boto3
import json

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    sqs = boto3.client("sqs")
    eventbridge = boto3.client("events")
    QUEUE_URL = os.getenv("USER_SERVICE_QUEUE")
    EVENT_BUS = os.getenv("EVENT_BUS_NAME")
else:
    print("Running in local mode; events will be printed")

# Make this async
async def publish_event(event_type: str, data: dict):
    if USE_AWS:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(data)
        )
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "user-service",
                    "DetailType": event_type,
                    "Detail": json.dumps(data),
                    "EventBusName": EVENT_BUS
                }
            ]
        )
    else:
        print(f"{event_type} event:", data)
