import os
import asyncio
import logging
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import stripe

from database import database, metadata, engine
from models import payments
from events import publish_event
from consumer import poll_orders
from database import init_db

# ─── Load environment ─────────────────────────────
load_dotenv()

app = FastAPI(title="Payment Service", version="1.2.0")

# ─── Logging ──────────────────────────────────────
logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# ─── Config ───────────────────────────────────────
USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# ✅ Hybrid mode — enable Stripe if key exists
USE_STRIPE = bool(STRIPE_SECRET_KEY)

if USE_STRIPE:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("💳 Stripe mode enabled (Hybrid mode ok).")
else:
    logger.info("🧪 Local/Simulated mode active (Stripe disabled).")

# ─── Models ───────────────────────────────────────
class PaymentRequest(BaseModel):
    order_id: str
    user_id: str | None = None
    amount: float

# ─── Health flag ───────────────────────────────────
last_poll_success = False

# ─── Background Poller ─────────────────────────────
async def monitored_poll_orders():
    global last_poll_success
    logger.info("🚀 Starting SQS poller for Payment Service...")
    while True:
        try:
            success = await poll_orders()
            last_poll_success = bool(success)
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            logger.warning("🛑 Poller cancelled.")
            break
        except Exception as e:
            last_poll_success = False
            logger.error(f"[ERROR] Poller loop failed: {e}")
            await asyncio.sleep(5)

# ─── API Routes ────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "payment-service", "status": "running"}

@app.get("/health")
async def health():
    return {
        "service": "payment-service",
        "status": "healthy" if last_poll_success else "degraded",
        "polling": last_poll_success,
        "stripe_enabled": USE_STRIPE,
        "aws_enabled": USE_AWS,
    }

# ─── Create PaymentIntent (Stripe) ─────────────────
@app.post("/create-intent")
async def create_payment_intent(request: PaymentRequest):
    """
    Called from frontend to create a Stripe PaymentIntent.
    """
    if not USE_STRIPE:
        raise HTTPException(status_code=400, detail="Stripe is disabled in this environment.")

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(request.amount * 100),  # cents
            currency="usd",
            metadata={
                "order_id": request.order_id,
                "user_id": request.user_id or "anonymous",
            },
        )
        logger.info(f"🧾 Created Stripe PaymentIntent for order {request.order_id}")
        return {"client_secret": intent.client_secret}
    except Exception as e:
        logger.error(f"[STRIPE ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Stripe Webhook ────────────────────────────────
@app.post("/webhook")
async def stripe_webhook(request: Request):
    if not USE_STRIPE:
        raise HTTPException(status_code=400, detail="Stripe disabled.")

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        order_id = intent["metadata"].get("order_id")
        user_id = intent["metadata"].get("user_id")
        amount = intent["amount_received"] / 100

        payment_id = str(uuid4())
        await database.execute(payments.insert().values(
            id=payment_id,
            order_id=order_id,
            amount=amount,
            status="paid"
        ))

        # publish to AWS event bus / queue
        await publish_event("payment.processed", {
            "payment_id": payment_id,
            "order_id": order_id,
            "user_id": user_id,
            "amount": amount,
            "status": "paid"
        })

        logger.info(f"✅ Stripe payment completed for order {order_id}")

    return {"status": "ok"}

# ─── Fallback Manual Payment Endpoint ──────────────
@app.post("/pay")
async def manual_pay(request: PaymentRequest):
    """Fallback simulation if Stripe is off."""
    payment_id = str(uuid4())
    await asyncio.sleep(1)
    await database.execute(payments.insert().values(
        id=payment_id,
        order_id=request.order_id,
        amount=request.amount,
        status="paid",
    ))
    await publish_event("payment.processed", {
        "payment_id": payment_id,
        "order_id": request.order_id,
        "status": "paid",
        "amount": request.amount,
    })
    return {"message": "Simulated payment successful"}

# ─── Startup / Shutdown ────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("[STARTUP] Connecting DB...")
    init_db()
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(monitored_poll_orders())

@app.on_event("shutdown")
async def shutdown():
    logger.info("[SHUTDOWN] Disconnecting DB...")
    await database.disconnect()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
