from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import drivers
from schemas import Driver, DriverCreate
from database import database, metadata, engine

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
    query = drivers.insert().values(id=driver_id, name=driver.name, license_number=driver.license_number, status="available")
    await database.execute(query)
    return Driver(id=driver_id, **driver.dict(), status="available")

@app.get("/drivers/{driver_id}", response_model=Driver)
async def get_driver(driver_id: str):
    query = drivers.select().where(drivers.c.id == driver_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="Driver not found")
    return Driver(**record)

@app.get("/health")
def health():
    return {"status": "driver-service healthy"}

