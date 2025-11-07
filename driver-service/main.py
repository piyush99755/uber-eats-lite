import asyncio
from fastapi import FastAPI
from uuid import uuid4
from typing import List, Optional
from database import database, metadata, engine
from models import drivers
from schemas import DriverCreate, Driver
from events import publish_event
from consumer import poll_messages  # background consumer
from fastapi import HTTPException

app = FastAPI(title="Driver Service")

# ------------------------
# Startup & Shutdown
# ------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    # Start consumer in background
    asyncio.create_task(poll_messages())

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# ------------------------
# Driver Endpoints
# ------------------------
@app.get("/drivers", response_model=List[Driver])
async def list_drivers(status: Optional[str] = None):
    query = drivers.select()
    if status:
        query = query.where(drivers.c.status == status)
    return await database.fetch_all(query)

@app.post("/drivers", response_model=Driver)
async def create_driver(driver: DriverCreate):
    driver_id = str(uuid4())
    query = drivers.insert().values(
        id=driver_id,
        name=driver.name,
        vehicle=driver.vehicle,
        license_number=driver.license_number,
        status="available"
    )
    await database.execute(query)

    # Publish driver.created event
    await publish_event("driver.created", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })

    return Driver(id=driver_id, status="available", **driver.dict())

@app.get("/health")
async def health():
    return {"status": "driver-service healthy"}


# DELETE DRIVER
@app.delete("/drivers/{driver_id}", tags=["Drivers"])
async def delete_driver(driver_id: str):
    query = drivers.select().where(drivers.c.id == driver_id)
    existing_driver = await database.fetch_one(query)
    if not existing_driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    delete_query = drivers.delete().where(drivers.c.id == driver_id)
    await database.execute(delete_query)

    await publish_event("driver.deleted", {"id": driver_id})
    return {"message": f"Driver {driver_id} deleted successfully"}

@app.put("/drivers/{driver_id}", response_model=Driver, tags=["Drivers"])
async def update_driver(driver_id: str, driver: DriverCreate):
    # Check if driver exists
    query = drivers.select().where(drivers.c.id == driver_id)
    existing_driver = await database.fetch_one(query)
    if not existing_driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    # Update driver
    update_query = drivers.update().where(drivers.c.id == driver_id).values(
        name=driver.name,
        vehicle=driver.vehicle,
        license_number=driver.license_number
    )
    await database.execute(update_query)

    # Publish event
    await publish_event("driver.updated", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle,
        "license_number": driver.license_number
    })

    return Driver(id=driver_id, status=existing_driver["status"], **driver.dict())