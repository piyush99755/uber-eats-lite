from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import drivers
from schemas import DriverCreate, Driver
from database import database, metadata, engine
from events import publish_event

app = FastAPI(title="Driver Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/drivers", response_model=Driver)
async def create_driver(driver: DriverCreate):
    driver_id = str(uuid4())
    query = drivers.insert().values(id=driver_id, name=driver.name, vehicle=driver.vehicle)
    await database.execute(query)
    
    await publish_event("driver.created", {
        "id": driver_id,
        "name": driver.name,
        "vehicle": driver.vehicle
    })
    
    return Driver(id=driver_id, **driver.dict())

@app.get("/health")
def health():
    return {"status": "driver-service healthy"}
