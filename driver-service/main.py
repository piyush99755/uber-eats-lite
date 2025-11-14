import asyncio
import uuid
import os
from fastapi import FastAPI, HTTPException, Request, Depends
from typing import List, Optional
from uuid import uuid4
from database import database, metadata, engine
from models import drivers
from schemas import DriverCreate, Driver
from events import publish_event
from consumer import poll_messages  # background consumer
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

# ---------------------------------------------------------
# EXISTING SERVICE CONFIG (kept as-is)
# ---------------------------------------------------------
app = FastAPI(title="Driver Service")

# Prometheus metrics
DRIVER_EVENTS_PROCESSED = Counter(
    "driver_events_processed_total", "Total driver-related events processed", ["event_type"]
)
ACTIVE_DRIVERS = Gauge(
    "active_drivers_total", "Current number of active (available) drivers"
)

# ---------------------------------------------------------
# MIDDLEWARE: Trace ID Propagation
# ---------------------------------------------------------
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response

# ---------------------------------------------------------
# STARTUP & SHUTDOWN (kept + extended logging)
# ---------------------------------------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    asyncio.create_task(poll_messages())
    print("[Driver Service] ✅ Connected to DB and consumer started.")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("[Driver Service] 🛑 Database disconnected.")

# ---------------------------------------------------------
# DEPENDENCIES (kept as-is)
# ---------------------------------------------------------
def get_current_user(request: Request):
    """
    Reads user info from API Gateway headers:
    x-user-id, x-user-role, x-trace-id
    """
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    return {"id": user_id, "role": role, "trace_id": trace_id}

def admin_required(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admins only")
    return user

# ---------------------------------------------------------
# ORIGINAL DRIVER ENDPOINTS (all kept intact)
# ---------------------------------------------------------
@app.get("/drivers", response_model=List[Driver])
async def list_drivers(status: Optional[str] = None, user=Depends(get_current_user)):
    query = drivers.select()
    if status:
        query = query.where(drivers.c.status == status)
    results = await database.fetch_all(query)
    ACTIVE_DRIVERS.set(len(results))
    return results  # Keep original behavior (no role restriction on GET)

@app.post("/drivers", response_model=Driver)
async def create_driver(driver: DriverCreate, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    driver_id = str(uuid4())
    query = drivers.insert().values(
        id=driver_id,
        name=driver.name,
        vehicle=driver.vehicle,
        license_number=driver.license_number,
        status="available"
    )
    await database.execute(query)

    await publish_event("driver.created", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })

    DRIVER_EVENTS_PROCESSED.labels(event_type="created").inc()
    print(f"[TRACE {trace_id}] Driver {driver_id} created by {user['id']}")
    return Driver(id=driver_id, status="available", **driver.dict())

@app.delete("/drivers/{driver_id}", tags=["Drivers"])
async def delete_driver(driver_id: str, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    query = drivers.select().where(drivers.c.id == driver_id)
    existing_driver = await database.fetch_one(query)
    if not existing_driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    delete_query = drivers.delete().where(drivers.c.id == driver_id)
    await database.execute(delete_query)

    await publish_event("driver.deleted", {"id": driver_id})
    DRIVER_EVENTS_PROCESSED.labels(event_type="deleted").inc()

    print(f"[TRACE {trace_id}] Driver {driver_id} deleted by {user['id']}")
    return {"message": f"Driver {driver_id} deleted successfully"}

@app.put("/drivers/{driver_id}", response_model=Driver, tags=["Drivers"])
async def update_driver(driver_id: str, driver: DriverCreate, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    query = drivers.select().where(drivers.c.id == driver_id)
    existing_driver = await database.fetch_one(query)
    if not existing_driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    update_query = drivers.update().where(drivers.c.id == driver_id).values(
        name=driver.name,
        vehicle=driver.vehicle,
        license_number=driver.license_number
    )
    await database.execute(update_query)

    await publish_event("driver.updated", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })

    DRIVER_EVENTS_PROCESSED.labels(event_type="updated").inc()
    print(f"[TRACE {trace_id}] Driver {driver_id} updated by {user['id']}")
    return Driver(id=driver_id, status=existing_driver["status"], **driver.dict())

# ---------------------------------------------------------
# HEALTH & METRICS ENDPOINTS (added safely)
# ---------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "driver-service healthy"}

@app.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
