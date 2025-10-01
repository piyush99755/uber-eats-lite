import os
import boto3

USE_AWS = os.getenv("USE_AWS", "False") == "True"

if USE_AWS:
    s3 = boto3.client("s3")
    BUCKET_NAME = os.getenv("ORDER_SERVICE_BUCKET")
else:
    LOCAL_STORAGE = "./local_storage/order-service"
    os.makedirs(LOCAL_STORAGE, exist_ok=True)

def save_file(file_name: str, data: bytes):
    if USE_AWS:
        s3.put_object(Bucket=BUCKET_NAME, Key=file_name, Body=data)
    else:
        with open(os.path.join(LOCAL_STORAGE, file_name), "wb") as f:
            f.write(data)
