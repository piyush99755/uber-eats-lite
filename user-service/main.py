import uuid
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

from database import database, metadata, engine
from models import users
from schemas import UserCreate, User
from events import publish_event
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="User Service")

# ------------------------
# CORS
# ------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",
        "*",  # testing only
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# Standard API Response
# ------------------------
class APIResponse(JSONResponse):
    def __init__(self, success: bool, data: Optional[any] = None, message: Optional[str] = None):
        content = {"success": success, "data": data, "message": message}
        super().__init__(content=content)

# ------------------------
# Exception Handling
# ------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return APIResponse(success=False, message=str(exc))

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
# Health & Readiness
# ------------------------
@app.get("/health")
async def health():
    return APIResponse(success=True, message="User service is alive")

@app.get("/ready")
async def readiness():
    try:
        await database.fetch_one("SELECT 1")
        return APIResponse(success=True, message="User service is ready")
    except Exception as e:
        return APIResponse(success=False, message=f"Not ready: {str(e)}")

# ------------------------
# User Endpoints
# ------------------------
@app.get("/users", response_class=APIResponse)
async def list_users():
    query = users.select()
    results = await database.fetch_all(query)
    return APIResponse(success=True, data=[dict(row) for row in results])

@app.get("/users/{user_id}", response_class=APIResponse)
async def get_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse(success=True, data=dict(record))

@app.post("/users", response_class=APIResponse)
async def create_user(user: UserCreate):
    user_id = str(uuid.uuid4())
    query = users.insert().values(id=user_id, name=user.name, email=user.email)
    await database.execute(query)

    try:
        await publish_event("user.created", {"id": user_id, "name": user.name, "email": user.email})
    except Exception as e:
        print(f"[Warning] Failed to publish user.created: {e}")

    return APIResponse(success=True, data={"id": user_id, **user.dict()}, message="User created")

@app.delete("/users/{user_id}", response_class=APIResponse)
async def delete_user(user_id: str):
    query = users.select().where(users.c.id == user_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")

    await database.execute(users.delete().where(users.c.id == user_id))

    try:
        await publish_event("user.deleted", {"id": user_id})
    except Exception as e:
        print(f"[Warning] Failed to publish user.deleted: {e}")

    return APIResponse(success=True, message=f"User {user_id} deleted successfully")
