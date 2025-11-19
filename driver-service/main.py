# driver-service/main.py
import asyncio
import uuid
import os
from fastapi import FastAPI, HTTPException, Request, Depends, Body
from typing import List, Optional, Dict, Any
from database import database, metadata, engine
from models import drivers
from schemas import DriverCreate, Driver
from pydantic import BaseModel
from events import publish_event
from consumer import start_consumers
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response, JSONResponse
import httpx
from jose import jwt, JWTError

# -------------------------
# App + metrics + config
# -------------------------
app = FastAPI(title="Driver Service")

DRIVER_EVENTS_PROCESSED = Counter(
    "driver_events_processed_total", "Total driver-related events processed", ["event_type"]
)
ACTIVE_DRIVERS = Gauge(
    "active_drivers_total", "Current number of active (available) drivers"
)

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")
JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# -------------------------
# Startup / shutdown
# -------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(start_consumers())
    print("[Driver Service] ✅ Started and connected.")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("[Driver Service] 🛑 Shutdown completed.")

# -------------------------
# Helpers: JWT decode & user extraction
# -------------------------
def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
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

# -------------------------
# Internal schema for auth-service
# -------------------------
class DriverInternalCreate(BaseModel):
    id: Optional[str] = None
    name: str
    email: Optional[str] = None
    vehicle: Optional[str] = None
    license_number: Optional[str] = None
    status: Optional[str] = "available"

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
    role = user.get("role")
    if user.get("id") is not None and role not in ("admin", "driver"):
        raise HTTPException(status_code=403, detail="Forbidden")

    trace_id = user.get("trace_id", str(uuid.uuid4()))
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
    print(f"[TRACE {trace_id}] Driver {driver_id} created")
    return Driver(id=driver_id, status="available", **driver.dict())

@app.get("/drivers/{driver_id}", response_model=Driver)
async def get_driver_by_id(driver_id: str, user=Depends(get_optional_user)):
    rec = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not rec:
        raise HTTPException(status_code=404, detail="Driver not found")
    return rec

@app.put("/drivers/{driver_id}", response_model=Driver)
async def update_driver(driver_id: str, driver: DriverCreate, user=Depends(admin_required)):
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Driver not found")

    await database.execute(
        drivers.update().where(drivers.c.id == driver_id).values(
            name=driver.name,
            vehicle=driver.vehicle,
            license_number=driver.license_number
        )
    )

    await publish_event("driver.updated", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })

    DRIVER_EVENTS_PROCESSED.labels(event_type="updated").inc()
    return Driver(id=driver_id, status=existing["status"], **driver.dict())

@app.delete("/drivers/{driver_id}")
async def delete_driver(driver_id: str, user=Depends(admin_required)):
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Driver not found")

    await database.execute(drivers.delete().where(drivers.c.id == driver_id))
    await publish_event("driver.deleted", {"id": driver_id})
    DRIVER_EVENTS_PROCESSED.labels(event_type="deleted").inc()
    return JSONResponse({"success": True, "message": "Driver deleted successfully"})

# -------------------------
# Internal registration (auth-service)
# -------------------------
@app.post("/internal/register")
async def internal_register_driver(payload: DriverInternalCreate = Body(...)):
    driver_id = payload.id or str(uuid.uuid4())
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))

    if existing:
        await database.execute(
            drivers.update().where(drivers.c.id == driver_id).values(
                name=payload.name,
                vehicle=payload.vehicle or existing.get("vehicle"),
                license_number=payload.license_number or existing.get("license_number"),
                status=payload.status or existing.get("status", "available")
            )
        )
        return {"message": "driver updated", "id": driver_id}

    await database.execute(
        drivers.insert().values(
            id=driver_id,
            name=payload.name,
            vehicle=payload.vehicle or "",
            license_number=payload.license_number or "",
            status=payload.status or "available"
        )
    )

    await publish_event("driver.created", {
        "id": driver_id,
        "name": payload.name,
        "vehicle": payload.vehicle,
        "license_number": payload.license_number
    })
    DRIVER_EVENTS_PROCESSED.labels(event_type="created").inc()
    return {"message": "driver created", "id": driver_id}

# -------------------------
# Driver self-service
# -------------------------
@app.get("/drivers/me")
async def get_my_profile(user=Depends(driver_required)):
    driver_id = user["id"]
    rec = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not rec:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return rec

@app.put("/drivers/me")
async def update_my_profile(driver: DriverCreate, user=Depends(driver_required)):
    driver_id = user["id"]
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not existing:
        return JSONResponse({"success": False, "message": "Driver not found"}, status_code=404)

    try:
        await database.execute(
            drivers.update().where(drivers.c.id == driver_id).values(
                name=driver.name,
                vehicle=driver.vehicle,
                license_number=driver.license_number
            )
        )
        await publish_event("driver.updated", {"id": driver_id, **driver.dict()})
        DRIVER_EVENTS_PROCESSED.labels(event_type="updated").inc()
        return JSONResponse({"success": True, "message": "Driver profile updated successfully"})
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Update failed: {e}"}, status_code=500)

@app.delete("/drivers/me")
async def delete_my_profile(user=Depends(driver_required)):
    driver_id = user["id"]
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not existing:
        return JSONResponse({"success": False, "message": "Driver not found"}, status_code=404)

    try:
        await database.execute(drivers.delete().where(drivers.c.id == driver_id))
        await publish_event("driver.deleted", {"id": driver_id})
        DRIVER_EVENTS_PROCESSED.labels(event_type="deleted").inc()
        return JSONResponse({"success": True, "message": "Driver profile deleted successfully"})
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Failed to delete profile: {e}"}, status_code=500)

class VehicleUpdate(BaseModel):
    vehicle: str

@app.put("/update-vehicle")
async def update_vehicle(body: VehicleUpdate, user=Depends(driver_required)):
    print("JWT user:", user)
    driver_id = user["id"]
    existing = await database.fetch_one(drivers.select().where(drivers.c.id == driver_id))
    if not existing:
        return JSONResponse({"success": False, "message": "Driver not found"}, status_code=404)

    try:
        await database.execute(
            drivers.update().where(drivers.c.id == driver_id).values(vehicle=body.vehicle)
        )
        await publish_event("driver.updated", {"id": driver_id, "vehicle": body.vehicle})
        DRIVER_EVENTS_PROCESSED.labels(event_type="updated").inc()
        return JSONResponse({"success": True, "message": "Vehicle updated successfully"})
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Update failed: {e}"}, status_code=500)

# -------------------------
# Orders
# -------------------------
@app.get("/my-orders")
async def get_my_orders(user=Depends(driver_required)):
    driver_id = user["id"]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ORDER_SERVICE_URL}/internal/driver-orders/{driver_id}")
            if resp.status_code == 200:
                return resp.json()
            return []
    except Exception as e:
        print(f"[DriverService] failed to fetch driver orders: {e}")
        return []

# -------------------------
# Health & metrics
# -------------------------
@app.get("/health")
async def health():
    return {"status": "driver-service healthy"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
