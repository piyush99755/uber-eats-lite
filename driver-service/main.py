from fastapi import FastAPI
from uuid import uuid4
from models import drivers
from schemas import DriverCreate, Driver
from database import database, metadata, engine
from events import publish_event
from typing import List
from typing import Optional

app = FastAPI(title="Driver Service")

# Startup: connect to DB and create tables
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

# Shutdown: disconnect DB
@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    
@app.get("/drivers", response_model=List[Driver])
async def list_drivers(status: Optional[str] = None):
    query = drivers.select()
    if status:
        query = query.where(drivers.c.status == status)
    driver_list = await database.fetch_all(query)
    return driver_list


# Create driver endpoint
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

# Health check
@app.get("/health")
def health():
    return {"status": "driver-service healthy"}
