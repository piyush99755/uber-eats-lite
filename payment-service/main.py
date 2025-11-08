import os
import asyncio
import logging
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import stripe

from database import database, metadata, engine
from models import payments
from events import publish_event
from consumer import poll_orders  # Your existing consumer logic
from database import init_db

# ─── Load environment ─────────────────────────────────────────────
load_dotenv()

# ─── FastAPI App ──────────────────────────────────────────────────
app = FastAPI(title="Payment Service", version="1.1.0")

# ─── Logging ──────────────────────────────────────────────────────
logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# ─── Stripe / Mode Config ─────────────────────────────────────────
USE_STRIPE = os.getenv("USE_STRIPE", "False").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if USE_STRIPE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("💳 Stripe mode enabled.")
else:
    logger.info("🧪 Local (non-Stripe) mode active.")

# ─── Health flag ──────────────────────────────────────────────────
last_poll_success = False

# ─── Pydantic Models ─────────────────────────────────────────────
class PaymentRequest(BaseModel):
    order_id: str
    user_id: str
    amount: float

# ─── Background Polling ──────────────────────────────────────────
async def monitored_poll_orders():
    global last_poll_success
    logger.info("🚀 Starting SQS poller for Payment Service...")
    while True:
        try:
            success = await poll_orders()
            last_poll_success = bool(success)
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            logger.warning("🛑 Poller task cancelled.")
            break
        except Exception as e:
            last_poll_success = False
            logger.error(f"[ERROR] Poller loop failed: {e}")
            await asyncio.sleep(5)

# ─── Payment Endpoint ────────────────────────────────────────────
@app.post("/pay")
async def create_payment(request: PaymentRequest):
    if not request.order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    payment_id = str(uuid4())
    status = "pending"

    try:
        # Stripe or local simulation
        if USE_STRIPE:
            try:
                charge = stripe.Charge.create(
                    amount=int(request.amount * 100),
                    currency="usd",
                    description=f"Payment for Order {request.order_id}",
                    source="tok_visa"
                )
                status = "paid" if charge["status"] == "succeeded" else "failed"
            except Exception as e:
                logger.error(f"[STRIPE ERROR] {e}")
                status = "failed"
        else:
            await asyncio.sleep(1)
            status = "paid"

        # Insert into DB
        await database.execute(payments.insert().values(
            id=payment_id,
            order_id=request.order_id,
            amount=request.amount,
            status=status
        ))
        logger.info(f"[PAYMENT] Payment {status.upper()} for Order {request.order_id}")

        # Publish event AFTER DB success
        event_type = "payment.processed" if status == "paid" else "payment.failed"
        await publish_event(event_type, {
            "payment_id": payment_id,
            "order_id": request.order_id,
            "user_id": request.user_id,
            "status": status,
            "amount": request.amount
        })

        if status == "paid":
            return {"message": "Payment successful", "payment_id": payment_id}
        else:
            raise HTTPException(status_code=400, detail="Payment failed")

    except Exception as e:
        logger.error(f"[ERROR] Payment creation failed: {e}")
        await publish_event("payment.failed", {
            "order_id": request.order_id,
            "user_id": request.user_id,
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"Payment error: {e}")

# ─── Health / Root ───────────────────────────────────────────────
@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {
        "service": "payment-service",
        "status": "healthy" if last_poll_success else "degraded",
        "polling": last_poll_success,
        "mode": "stripe" if USE_STRIPE else "local"
    }

@app.get("/")
def root():
    return {"service": "payment-service", "status": "running"}

@app.get("/payments/{user_id}")
async def get_user_payments(user_id: str):
    query = payments.select().where(payments.c.user_id == user_id)
    results = await database.fetch_all(query)
    return [dict(row) for row in results]


# ─── Startup / Shutdown ─────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("[STARTUP] Connecting database...")
    init_db()
    await database.connect()
    metadata.create_all(engine)
    logger.info("[STARTUP] Database connected and tables ensured.")
    asyncio.create_task(monitored_poll_orders())

@app.on_event("shutdown")
async def shutdown():
    logger.info("[SHUTDOWN] Disconnecting database...")
    await database.disconnect()
    logger.info("[SHUTDOWN] Database disconnected.")

# ─── Entry Point ────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
