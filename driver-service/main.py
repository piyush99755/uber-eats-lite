import asyncio
import uuid
import os
from fastapi import FastAPI, HTTPException, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
from typing import List, Optional, Dict, Any
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from jose import jwt, JWTError

from database import database, metadata, engine
from models import metadata, drivers
from schemas import DriverCreate, Driver
from events import publish_event
from consumer import start_driver_consumer
from metrics import DRIVER_EVENTS_PROCESSED, ACTIVE_DRIVERS  # import metrics

# -------------------------
# FastAPI app
# -------------------------
app = FastAPI(title="Driver Service")

# Config
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")
JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# CORS (allow your API Gateway)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Startup / Shutdown
# -------------------------
@app.on_event("startup")
async def startup():
    print("[Driver Service] Starting up...")
    metadata.create_all(engine)  # Ensure tables exist
    await database.connect()
    print("[Driver Service] DB connected.")
    asyncio.create_task(start_driver_consumer())
    print("[Driver Service] Consumer started in background")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("[Driver Service] DB disconnected.")

# -------------------------
# JWT / Auth helpers
# -------------------------
def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

async def get_optional_user(request: Request) -> Dict[str, Optional[str]]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    if not auth or not auth.lower().startswith("bearer "):
        return {"id": None, "role": None, "trace_id": trace_id}
    token = auth.split(" ", 1)[1].strip()
    payload = decode_jwt_token(token)
    if not payload:
        return {"id": None, "role": None, "trace_id": trace_id}
    return {"id": payload.get("sub"), "role": payload.get("role"), "trace_id": trace_id}

def driver_required(user=Depends(get_optional_user)):
    if not user or user.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Drivers only")
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="Missing user id")
    return user

def admin_required(user=Depends(get_optional_user)):
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

@app.post("/internal/register", response_model=Driver)
async def register_driver(driver: DriverCreate, id: str = None):
    """
    Register a new driver (called internally by auth-service).
    """
    driver_id = id or str(uuid4())
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

    # Return the driver with correct status
    return {**driver.dict(), "id": driver_id, "status": "available"}

@app.get("/drivers/{driver_id}", response_model=Driver)
async def get_driver(driver_id: str):
    query = drivers.select().where(drivers.c.id == driver_id)
    result = await database.fetch_one(query)
    if not result:
        raise HTTPException(status_code=404, detail="Driver not found")
    return dict(result)
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
# Health / Metrics
# -------------------------
@app.get("/health")
async def health():
    return {"status": "driver-service healthy"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
