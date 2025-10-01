from fastapi import FastAPI, HTTPException
from uuid import uuid4
from models import users
from schemas import UserCreate, User
from database import database, metadata, engine
from events import publish_event

app = FastAPI(title="User Service")

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/users", response_model=User)
async def create_user(user: UserCreate):
    user_id = str(uuid4())
    query = users.insert().values(id=user_id, name=user.name, email=user.email)
    await database.execute(query)
    
    await publish_event("user.created", {
        "id": user_id,
        "name": user.name,
        "email": user.email
    })
    
    return User(id=user_id, **user.dict())

@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user_record)

@app.get("/health")
def health():
    return {"status": "user-service healthy"}
