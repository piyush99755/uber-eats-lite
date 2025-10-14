import asyncio
from fastapi import FastAPI
from consumer import poll_orders
from database import database, metadata, engine

app = FastAPI(title="Payment Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(poll_orders())  # Start real order polling

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.get("/health")
def health():
    return {"status": "payment-service healthy"}
