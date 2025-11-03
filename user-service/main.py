import uuid
from fastapi import FastAPI, HTTPException
from typing import List
from database import database, metadata, engine
from models import users
from schemas import UserCreate, User
from events import publish_event

app = FastAPI(title="User Service")

from fastapi.middleware.cors import CORSMiddleware

# Allow frontend and gateway to access this service
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # local frontend
        "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",  # ALB
        "*"  # for testing; remove later in prod
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

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ------------------------
# Health Check
# ------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "user-service"}


# ------------------------
# Create User
# ------------------------
# ------------------------
# Create User
# ------------------------
@app.post("/users", response_model=User)
async def create_user(user: UserCreate):
    """
    Create a new user and publish a user.created event.
    """
    user_id = str(uuid.uuid4())

    query = users.insert().values(
        id=user_id,
        name=user.name,
        email=user.email
    )
    await database.execute(query)

    # Try to publish event but don't crash if it fails
    try:
        await publish_event("user.created", {
            "id": user_id,
            "name": user.name,
            "email": user.email
        })
    except Exception as e:
        print(f"[Warning] Failed to publish event: {e}")

    return User(id=user_id, **user.dict())


# ------------------------
# Get All Users
# ------------------------
@app.get("/users", response_model=List[User])
async def list_users():
    """
    Return all users in the system.
    """
    query = users.select()
    results = await database.fetch_all(query)
    return [User(**dict(row)) for row in results]


# ------------------------
# Get User by ID
# ------------------------
@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    """
    Return details of a single user by ID.
    """
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**dict(user_record))
