from fastapi import FastAPI, HTTPException
from sqlalchemy import select
from uuid import uuid4
from models import users
from schemas import UserCreate, User
from database import engine, metadata
from databases import Database

app = FastAPI(title="User Service")

DATABASE_URL = "sqlite:///./user_service.db"
database = Database(DATABASE_URL)

@app.on_event("startup")
async def startup():
    await database.connect()
    # create tables if not exist
    from database import engine, metadata
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/users", response_model=User)
async def create_user(user: UserCreate):
    user_id = str(uuid4())
    query = users.insert().values(id=user_id, name=user.name, email=user.email)
    await database.execute(query)
    return User(id=user_id, **user.dict())

@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user_record)

@app.get("/users")
async def list_users():
    query = users.select()
    return await database.fetch_all(query)

@app.get("/health")
def health():
    return {"status": "user-service healthy"}

