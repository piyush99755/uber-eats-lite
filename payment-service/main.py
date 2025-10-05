import asyncio
from fastapi import FastAPI
from consumer import poll_orders
from database import database, metadata, engine
from dotenv import load_dotenv
import os

load_dotenv()

USE_AWS = os.getenv("USE_AWS", "False").lower() in ("true", "1", "yes")
print("USE_AWS =", USE_AWS)

app = FastAPI(title="Payment Service")


@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    # Start background task to listen for OrderCreated
    asyncio.create_task(poll_orders())


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.get("/health")
def health():
    return {"status": "payment-service healthy"}
