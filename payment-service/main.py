import os
import asyncio
import logging
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from pydantic import BaseModel
from dotenv import load_dotenv
import stripe
import jwt  # PyJWT
from database import database, metadata, engine, init_db
from models import payments
from events import publish_event
from consumer import poll_orders

# ─── Load environment ─────────────────────────────
load_dotenv()  # only loads .env if present, AWS env vars still take precedence

# ─── JWT / Auth config ───────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")  # should match your API Gateway / auth secret

# ─── FastAPI App ─────────────────────────────────
app = FastAPI(title="Payment Service", version="1.2.0")

# ─── Logging ─────────────────────────────────────
logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# ─── Config ───────────────────────────────────────
STRIPE_MODE = os.getenv("STRIPE_MODE", "local").lower()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
USE_STRIPE = STRIPE_MODE == "stripe" and bool(STRIPE_SECRET_KEY)

USE_AWS = os.getenv("USE_AWS", "False").lower() == "true"

# Log environment for debugging
logger.info(f"[ENV] STRIPE_MODE={STRIPE_MODE}")
logger.info(f"[ENV] STRIPE_SECRET_KEY={'set' if STRIPE_SECRET_KEY else 'not set'}")
logger.info(f"[ENV] USE_AWS={USE_AWS}")

if USE_STRIPE:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info("💳 Stripe mode enabled")
else:
    logger.info("🧪 Local/Simulated mode active (Stripe disabled)")

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
            logger.warning("🛑 Poller cancelled")
            break
        except Exception as e:
            last_poll_success = False
            logger.error(f"[ERROR] Poller loop failed: {e}")
            await asyncio.sleep(5)

# ─── Dependencies ─────────────────────────────────
def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        role = payload.get("role")
        trace_id = str(uuid4())
        if not user_id or not role:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return {"id": user_id, "role": role, "trace_id": trace_id}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def admin_required(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admins only")
    return user

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

@app.post("/create-intent")
async def create_payment_intent(request: PaymentRequest, user=Depends(get_current_user)):
    trace_id = user["trace_id"]
    if not USE_STRIPE:
        raise HTTPException(status_code=400, detail="Stripe is disabled")

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(request.amount * 100),
            currency="usd",
            metadata={
                "order_id": request.order_id,
                "user_id": user["id"],
            },
        )
        logger.info(f"[TRACE {trace_id}] Created PaymentIntent for order {request.order_id}")
        return {"client_secret": intent.client_secret}
    except Exception as e:
        logger.error(f"[TRACE {trace_id}] [STRIPE ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pay")
async def manual_pay(request: PaymentRequest, user=Depends(get_current_user)):
    trace_id = user["trace_id"]
    payment_id = str(uuid4())
    await asyncio.sleep(1)  # simulate processing
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
        "user_id": user["id"],
    }, trace_id=trace_id)

    logger.info(f"[TRACE {trace_id}] Simulated payment successful for order {request.order_id}")
    return {"message": "Simulated payment successful"}

@app.get("/payments")
async def list_payments(user=Depends(get_current_user)):
    rows = await database.fetch_all(payments.select())
    return [dict(row) for row in rows]

@app.get("/list")
async def list_payments_desc(user=Depends(get_current_user)):
    query = payments.select().order_by(payments.c.id.desc())
    results = await database.fetch_all(query)
    return results

# ─── Startup / Shutdown ────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("[STARTUP] Connecting DB...")
    init_db()
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(monitored_poll_orders())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("[SHUTDOWN] Disconnecting DB...")
    await database.disconnect()

# ─── Main entrypoint ──────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
