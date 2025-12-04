import asyncio
import uuid
import os
from fastapi import FastAPI, HTTPException, Request, Depends, Response, Path, Body, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from jose import jwt, JWTError
from ws_manager import connect_client, disconnect_client
from database import database, metadata, engine
from models import drivers, driver_orders, driver_orders_history
from schemas import DriverCreate, Driver
from events import publish_event
from consumer import start_driver_consumer
from metrics import DRIVER_EVENTS_PROCESSED, ACTIVE_DRIVERS
import logging

logger = logging.getLogger("driver-service")
logger.setLevel(logging.INFO)


# -------------------------
# FastAPI app
# -------------------------
app = FastAPI(title="Driver Service")

# Config
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")
JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

DRIVER_QUEUE_URL = os.getenv("DRIVER_QUEUE_URL")
if not DRIVER_QUEUE_URL:
    raise RuntimeError("❌ DRIVER_QUEUE_URL is missing in environment variables!")

# CORS (allow your API Gateway)
origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
async def safe_start_driver_consumer():
    while True:
        try:
            logger.info("📥 Starting SQS consumer loop...")
            await start_driver_consumer()
        except Exception as e:
            logger.error(f"🔥 SQS consumer crashed: {e}")
            await asyncio.sleep(5)

# -------------------------
# Startup / Shutdown
# -------------------------
@app.on_event("startup")
async def startup():
    # Connect DB
    await database.connect()
    logger.info("📦 Driver Service DB connected.")

    # Start SQS Consumer
    logger.info(f"🚀 Starting SQS consumer for Driver Service… Queue = {DRIVER_QUEUE_URL}")
    asyncio.create_task(safe_start_driver_consumer())


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# -------------------------
# JWT / Auth helpers
# -------------------------
def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

async def get_optional_user(request: Request) -> Dict[str, Optional[str]]:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))

    if not auth or not auth.lower().startswith("bearer "):
        return {"id": None, "role": None, "trace_id": trace_id}

    token = auth.split(" ", 1)[1].strip()
    payload = decode_jwt_token(token)

    if not payload:
        return {"id": None, "role": None, "trace_id": trace_id}

    return {
        "id": payload.get("sub"),  # JWT sub must match drivers.id
        "role": payload.get("role"),
        "trace_id": trace_id
    }

def admin_required(user=Depends(get_optional_user)):
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

async def driver_required(user=Depends(get_optional_user)):
    role = user.get("role")
    driver_id = user.get("id")
    trace_id = user.get("trace_id", "no-trace")

    print(f"[DEBUG][{trace_id}] driver_required called with role={role}, driver_id={driver_id}")

    if role not in ["driver", "Driver", "DRIVER"]:
        print(f"[DEBUG][{trace_id}] Access denied: role not driver")
        raise HTTPException(status_code=403, detail="Drivers only")

    if not driver_id:
        print(f"[DEBUG][{trace_id}] Missing driver ID in token")
        raise HTTPException(status_code=401, detail="Missing driver id in token")

    query = drivers.select().where(drivers.c.id == driver_id)
    driver = await database.fetch_one(query)
    if not driver:
        print(f"[DEBUG][{trace_id}] Driver not found in DB for id={driver_id}")
        raise HTTPException(status_code=404, detail="Driver not found")

    print(f"[DEBUG][{trace_id}] Driver found: {driver}")
    return user

# -------------------------
# Internal registration
# -------------------------
@app.post("/internal/register", response_model=Driver)
async def register_driver(driver: DriverCreate, id: str = None):
    driver_id = id or str(uuid.uuid4())
    query = insert(drivers).values(
        id=driver_id,
        name=driver.name,
        vehicle=driver.vehicle,
        license_number=driver.license_number,
        status="available"
    )
    try:
        with engine.connect() as conn:
            conn.execute(query)
            conn.commit()
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Driver already exists")
    return {**driver.dict(), "id": driver_id, "status": "available"}

# -------------------------
# CRUD endpoints
# -------------------------
@app.get("/drivers", response_model=List[Driver])
async def list_drivers(status: Optional[str] = None, user=Depends(get_optional_user)):
    query = drivers.select()
    if status:
        query = query.where(drivers.c.status == status)
    results = await database.fetch_all(query)
    ACTIVE_DRIVERS.set(len(results))
    return results

@app.post("/drivers", response_model=Driver)
async def create_driver(driver: DriverCreate, user=Depends(get_optional_user)):
    driver_id = driver.id or str(uuid.uuid4())
    await database.execute(
        drivers.insert().values(
            id=driver_id,
            name=driver.name,
            vehicle=driver.vehicle,
            license_number=driver.license_number,
            status="available"
        )
    )
    await publish_event("driver.created", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })
    DRIVER_EVENTS_PROCESSED.labels(event_type="created").inc()
    return Driver(id=driver_id, status="available", **driver.dict())

# -------------------------
# Driver-specific endpoints
# -------------------------
@app.get("/drivers/{driver_id}/me")
async def get_my_driver_profile(user=Depends(driver_required)):
    driver_id = user["id"]
    print(f"[DEBUG] Fetching profile for driver_id={driver_id}")

    query = drivers.select().where(drivers.c.id == driver_id)
    driver = await database.fetch_one(query)
    print(f"[DEBUG] driver record: {driver}")

    active_query = driver_orders.select().where(
        (driver_orders.c.driver_id == driver_id) & (driver_orders.c.status != "delivered")
    )
    active_deliveries = await database.fetch_all(active_query)
    print(f"[DEBUG] active_deliveries count: {len(active_deliveries)}")

    delivered_query = driver_orders_history.select().where(
        driver_orders_history.c.driver_id == driver_id
    ).order_by(driver_orders_history.c.created_at.desc())
    delivered_orders = await database.fetch_all(delivered_query)
    print(f"[DEBUG] delivered_orders count: {len(delivered_orders)}")

    return {
        "id": driver["id"],
        "name": driver["name"],
        "vehicle": driver["vehicle"],
        "license_number": driver["license_number"],
        "status": driver["status"],
        "active_deliveries": len(active_deliveries),
        "delivered_orders": len(delivered_orders),
    }


@app.get("/drivers/{driver_id}/deliveries/history")
async def get_driver_history(driver_id: str, user=Depends(driver_required)):
    trace_id = user.get("trace_id", "no-trace")
    print(f"[DEBUG][{trace_id}] Received request for delivery history of driver_id={driver_id}")

    if driver_id != user["id"]:
        print(f"[DEBUG][{trace_id}] Access denied: driver_id in token does not match requested driver_id")
        raise HTTPException(status_code=403, detail="Access denied")

    query = driver_orders_history.select().where(
        (driver_orders_history.c.driver_id == driver_id) & (driver_orders_history.c.status == "delivered")
    ).order_by(driver_orders_history.c.created_at.desc())

    try:
        rows = await database.fetch_all(query)
        print(f"[DEBUG][{trace_id}] Found {len(rows)} delivered orders for driver_id={driver_id}")
    except Exception as e:
        print(f"[ERROR][{trace_id}] Failed to fetch from driver_orders_history: {e}")
        raise HTTPException(status_code=500, detail="Database query failed")

    result = [dict(row) for row in rows]
    print(f"[DEBUG][{trace_id}] Returning response: {result}")
    return result


# -------------------------
# Profile + update + delete
# -------------------------
@app.get("/drivers/{driver_id}", response_model=Driver)
async def get_driver_profile(driver_id: str = Path(...), user=Depends(driver_required)):
    if driver_id != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    query = drivers.select().where(drivers.c.id == driver_id)
    driver = await database.fetch_one(query)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    active_query = driver_orders.select().where(
        (driver_orders.c.driver_id == driver_id) & (driver_orders.c.status != "delivered")
    )
    active_deliveries = await database.fetch_all(active_query)

    delivered_query = driver_orders_history.select().where(
        (driver_orders_history.c.driver_id == driver_id) & (driver_orders_history.c.status == "delivered")
    )
    delivered_orders = await database.fetch_all(delivered_query)

    return {**dict(driver), "active_deliveries": len(active_deliveries), "delivered_orders": len(delivered_orders)}

@app.put("/drivers/{driver_id}")
async def update_driver_profile(
    driver_id: str = Path(...), vehicle: str = Body(..., embed=True), user=Depends(driver_required)
):
    if driver_id != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    query = drivers.update().where(drivers.c.id == driver_id).values(vehicle=vehicle)
    await database.execute(query)
    return {"success": True, "message": "Vehicle updated"}

@app.delete("/drivers/{driver_id}")
async def delete_driver_profile(driver_id: str = Path(...), user=Depends(driver_required)):
    if driver_id != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    await database.execute(drivers.delete().where(drivers.c.id == driver_id))
    return {"success": True, "message": "Driver profile deleted"}

@app.websocket("/ws/drivers")
async def driver_ws(websocket: WebSocket):
    await connect_client(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            # Heartbeat / echo
            await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        await disconnect_client(websocket)
# -------------------------
# Health / Metrics
# -------------------------
@app.get("/health")
async def health():
    return {"status": "driver-service healthy"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
