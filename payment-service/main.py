from fastapi import FastAPI
import asyncio
from consumer import poll_orders
from database import database, metadata, engine

app = FastAPI(title="Payment Service")

last_poll_success = False  # shared health indicator

async def monitored_poll_orders():
    global last_poll_success
    try:
        while True:
            success = await poll_orders()
            last_poll_success = bool(success)
            await asyncio.sleep(5)
    except Exception:
        last_poll_success = False

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(monitored_poll_orders())

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.get("/health")
def health():
    if last_poll_success:
        return {"status": "payment-service healthy"}
    else:
        return {"status": "payment-service down"}
