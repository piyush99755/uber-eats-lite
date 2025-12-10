import os
import asyncio
import logging
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket
from pydantic import BaseModel
from dotenv import load_dotenv
import stripe
import jwt
import httpx
from database import database, metadata, engine, init_db
from models import payments
from events import publish_event, connected_clients, broadcast_payment_event
from consumer import poll_orders

# ───────────────────────────────────────────────────────────
# Load environment
# ───────────────────────────────────────────────────────────
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")

app = FastAPI(title="Payment Service", version="2.0.0")

# Logging
logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Stripe config
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY must be set in environment for real payments")
stripe.api_key = STRIPE_SECRET_KEY
logger.info("💳 Stripe mode enabled")

# ───────────────────────────────────────────────────────────
# Models
# ───────────────────────────────────────────────────────────
class PaymentRequest(BaseModel):
    order_id: str
    amount: float

class ConfirmPaymentRequest(BaseModel):
    payment_intent_id: str
    order_id: str

# ───────────────────────────────────────────────────────────
# Auth
# ───────────────────────────────────────────────────────────
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
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ───────────────────────────────────────────────────────────
# Health Monitoring
# ───────────────────────────────────────────────────────────
last_poll_success = False

async def monitored_poll_orders():
    global last_poll_success
    logger.info("🚀 Starting SQS poller for Payment Service...")
    while True:
        try:
            ok = await poll_orders()
            last_poll_success = bool(ok)
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[POLL ERROR] {e}")
            last_poll_success = False
            await asyncio.sleep(5)

# ───────────────────────────────────────────────────────────
# Routes
# ───────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "payment-service", "status": "running"}

@app.get("/health")
async def health():
    return {
        "service": "payment-service",
        "status": "healthy" if last_poll_success else "degraded",
        "polling": last_poll_success,
        "stripe_enabled": True,
    }

@app.post("/create-intent")
async def create_payment_intent(request: PaymentRequest, user=Depends(get_current_user)):
    trace_id = user["trace_id"]
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(request.amount * 100),
            currency="usd",
            payment_method_types=["card"],
            metadata={"order_id": request.order_id, "user_id": user["id"]}
        )
        logger.info(f"[TRACE {trace_id}] PaymentIntent created for order {request.order_id}")
        return {"client_secret": intent.client_secret, "status": intent.status}
    except Exception as e:
        logger.error(f"[STRIPE ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/confirm-payment")
async def confirm_payment(req: ConfirmPaymentRequest, user=Depends(get_current_user)):
    """
    Confirm a Stripe PaymentIntent, save the payment record idempotently,
    update the order-service immediately (so UI updates), then publish
    payment.completed for async driver assignment.
    """
    trace_id = user["trace_id"]

    # 1) Retrieve PaymentIntent from Stripe
    try:
        intent = stripe.PaymentIntent.retrieve(req.payment_intent_id)
    except Exception as e:
        logger.error(f"[TRACE {trace_id}] Stripe retrieval error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve payment intent")

    if intent.status != "succeeded":
        logger.warning(f"[TRACE {trace_id}] PaymentIntent not succeeded: {intent.status}")
        raise HTTPException(status_code=400, detail="Payment not successful")

    amount = (intent.amount or 0) / 100.0

    # 2) Idempotent insert/update into `payments` table
    try:
        existing = await database.fetch_one(
            payments.select().where(payments.c.order_id == req.order_id)
        )

        if existing:
            payment_id = existing["id"]
            logger.info(
                f"[TRACE {trace_id}] Payment already exists for order {req.order_id} (id={payment_id}), skipping insert."
            )
        else:
            payment_id = str(uuid4())
            await database.execute(
                payments.insert().values(
                    id=payment_id,
                    order_id=req.order_id,
                    amount=amount,
                    status="paid",
                    user_id=user["id"]
                )
            )
            logger.info(
                f"[TRACE {trace_id}] Payment saved to DB for order {req.order_id} (payment_id={payment_id})"
            )
    except Exception as e:
        logger.exception(f"[TRACE {trace_id}] DB error while saving payment: {e}")
        raise HTTPException(status_code=500, detail="Failed to save payment record")

    # 3) Synchronously update order-service (ensures UI stops showing 'pending')
    ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {
                "x-user-id": user["id"],
                "x-user-role": user.get("role", "service"),
                "x-trace-id": trace_id,
            }

            resp = await client.put(
                f"{ORDER_SERVICE_URL}/orders/{req.order_id}",
                json={"payment_status": "paid", "status": "paid"},
                headers=headers,
            )

            if resp.status_code not in (200, 201, 204):
                logger.warning(
                    f"[TRACE {trace_id}] order-service returned {resp.status_code}: {resp.text}"
                )
            else:
                logger.info(
                    f"[TRACE {trace_id}] Order-service updated order {req.order_id} → paid"
                )

    except Exception as e:
        logger.exception(
            f"[TRACE {trace_id}] Failed to update order-service for {req.order_id}: {e}"
        )
        # do NOT raise — event will still be published

    # 4) Publish event so driver-service can assign a driver
    try:
        await publish_event(
            "payment.completed",
            {
                "payment_id": payment_id,
                "order_id": req.order_id,
                "status": "paid",
                "amount": amount,
                "user_id": user["id"],
            },
            trace_id=trace_id,
        )

        logger.info(
            f"[TRACE {trace_id}] payment.completed published for order {req.order_id}"
        )
    except Exception as e:
        logger.exception(
            f"[TRACE {trace_id}] Failed to publish payment.completed for {req.order_id}: {e}"
        )

    return {"message": "Payment confirmed and order marked as paid"}

@app.get("/payments")
async def list_payments(user=Depends(get_current_user)):
    rows = await database.fetch_all(payments.select().where(payments.c.user_id == user["id"]))
    return [dict(r) for r in rows]

# ───────────────────────────────────────────────────────────
# WebSocket
# ───────────────────────────────────────────────────────────
@app.websocket("/ws/payments")
async def payments_ws(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # no incoming messages expected
    except:
        pass
    finally:
        connected_clients.discard(websocket)

# ───────────────────────────────────────────────────────────
# Startup / Shutdown
# ───────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("[STARTUP] Connecting DB...")
    init_db()
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(monitored_poll_orders())

@app.on_event("shutdown")
async def shutdown_event():
    await database.disconnect()

# ───────────────────────────────────────────────────────────
# Entrypoint
# ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
