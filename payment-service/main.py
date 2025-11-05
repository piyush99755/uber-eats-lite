import os
import asyncio
import logging
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import stripe
from consumer import poll_orders
from database import database, metadata, engine
from models import payments
from events import publish_event
from database import init_db

# ─── Load environment ─────────────────────────────────────────────
load_dotenv()

app = FastAPI(title="Payment Service", version="1.1.0")

# ─── Configs ─────────────────────────────────────────────────────
USE_STRIPE = os.getenv("USE_STRIPE", "False").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

if USE_STRIPE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    print("[PAYMENT] 💳 Stripe mode enabled.")
else:
    print("[PAYMENT] 🧪 Local (non-Stripe) mode active.")

# ─── Logging Setup ───────────────────────────────────────────────
logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# ─── Health Indicator ────────────────────────────────────────────
last_poll_success = False


# ─── Pydantic Model ──────────────────────────────────────────────
class PaymentRequest(BaseModel):
    order_id: str
    user_id: str
    amount: float


# ─── Background Polling Task ─────────────────────────────────────
async def monitored_poll_orders():
    """Background task to continuously poll SQS for order.created events."""
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


# ─── Manual Payment Endpoint ─────────────────────────────────────
@app.post("/pay")
async def create_payment(request: PaymentRequest):
    """Manual trigger for processing a payment (local/test)."""
    payment_id = str(uuid4())
    order_id = request.order_id
    user_id = request.user_id
    amount = request.amount
    status = "pending"

    logger.info(f"[PAYMENT] 🔄 Processing manual payment for Order {order_id} (${amount})")

    try:
        # Stripe integration
        if USE_STRIPE:
            try:
                charge = stripe.Charge.create(
                    amount=int(amount * 100),
                    currency="usd",
                    description=f"Payment for Order {order_id}",
                    source="tok_visa",  # Test token for Stripe sandbox
                )
                status = "paid" if charge["status"] == "succeeded" else "failed"
            except Exception as stripe_err:
                logger.error(f"[STRIPE ERROR] {stripe_err}")
                status = "failed"
        else:
            # Local simulation
            await asyncio.sleep(1)
            status = "paid"

        # Save record to DB
        query = payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status=status,
        )
        await database.execute(query)

        logger.info(f"[PAYMENT] ✅ Payment {status.upper()} for Order {order_id}")

        # Publish event
        event_type = "payment.processed" if status == "paid" else "payment.failed"
        await publish_event(event_type, {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "amount": amount
        })

        if status == "paid":
            return {"message": "Payment successful", "payment_id": payment_id}
        else:
            raise HTTPException(status_code=400, detail="Payment failed")

    except Exception as e:
        logger.error(f"[ERROR] Manual payment failed: {e}")
        await publish_event("payment.failed", {
            "order_id": order_id,
            "user_id": user_id,
            "error": str(e)
        })
        raise HTTPException(status_code=500, detail=f"Payment error: {e}")


# ─── Health & Utility Routes ─────────────────────────────────────
@app.get("/health", response_class=JSONResponse)
async def health_check():
    """Health check for Payment Service."""
    # Local mode (no Stripe/SQS)
    if not USE_STRIPE:
        return {
            "service": "payment-service",
            "status": "healthy",
            "polling": True,
            "mode": "local"
        }

    # AWS/Stripe mode
    status = "healthy" if last_poll_success else "degraded"
    return {
        "service": "payment-service",
        "status": status,
        "polling": last_poll_success,
        "mode": "aws"
    }


@app.get("/")
def root():
    """Root route for sanity check."""
    return {"service": "payment-service", "status": "running"}


# ─── Lifecycle Hooks ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("[STARTUP] Connecting database...")
    init_db()
    await database.connect()

    # ✅ Make sure the table exists in Postgres
    try:
        metadata.create_all(engine)
        logger.info("[STARTUP] Ensured all tables exist (payments).")
    except Exception as e:
        logger.error(f"[DB INIT ERROR] {e}")

    logger.info("[STARTUP] Database connected.")

    asyncio.create_task(monitored_poll_orders())
    logger.info("[STARTUP] Background poller started.")


@app.on_event("shutdown")
async def shutdown():
    logger.info("[SHUTDOWN] Disconnecting database...")
    await database.disconnect()
    logger.info("[SHUTDOWN] Database disconnected.")


# ─── Entrypoint ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
