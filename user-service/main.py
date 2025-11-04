import uuid
import os
from fastapi import FastAPI, HTTPException
from typing import List
from database import database, metadata, engine
from models import users
from schemas import UserCreate, User
from events import publish_event
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

app = FastAPI(title="User Service")

# ------------------------
# CORS (for local + ALB)
# ------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",
        "*"  # testing only
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------
# Startup & Shutdown
# ------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    print("[User Service] Connected to database and ready.")


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("[User Service] Database disconnected.")


# ------------------------
# Health Check
# ------------------------
@app.get("/users/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "user-service"}


# ------------------------
# Create User
# ------------------------
@app.post("/users", response_model=User, tags=["Users"])
async def create_user(user: UserCreate):
    """
    Create a new user and publish a user.created event to AWS SQS/EventBridge.
    """
    user_id = str(uuid.uuid4())

    query = users.insert().values(
        id=user_id,
        name=user.name,
        email=user.email
    )
    await database.execute(query)

    event_payload = {
        "id": user_id,
        "name": user.name,
        "email": user.email
    }

    try:
        await publish_event("user.created", event_payload)
        print(f"[Event Published] user.created -> {event_payload}")
    except Exception as e:
        print(f"[Warning] Failed to publish user.created: {e}")

    return User(id=user_id, **user.dict())


# ------------------------
# List All Users
# ------------------------
@app.get("/users", response_model=List[User], tags=["Users"])
async def list_users():
    query = users.select()
    results = await database.fetch_all(query)
    return [User(**dict(row)) for row in results]


# ------------------------
# Get User by ID
# ------------------------
@app.get("/users/{user_id}", response_model=User, tags=["Users"])
async def get_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**dict(record))


# ------------------------
# Delete User
# ------------------------
@app.delete("/users/{user_id}", tags=["Users"])
async def delete_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")

    await database.execute(users.delete().where(users.c.id == user_id))

    try:
        await publish_event("user.deleted", {"id": user_id})
        print(f"[Event Published] user.deleted -> {user_id}")
    except Exception as e:
        print(f"[Warning] Failed to publish user.deleted: {e}")

    return {"message": f"User {user_id} deleted successfully"}
