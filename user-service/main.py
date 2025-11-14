import uuid
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from database import database, metadata, engine
from models import users
from schemas import UserCreate
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
        "*",
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
    trace_id = getattr(request.state, "trace_id", "N/A")
    print(f"[TRACE {trace_id}] Exception: {exc}")
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
# Dependency: Current User
# ------------------------
def get_current_user(request: Request):
    """
    Reads user info from API Gateway headers:
    x-user-id, x-user-role, x-trace-id
    """
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id

    if not user_id or not role:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing user headers from gateway")
    return {"id": user_id, "role": role, "trace_id": trace_id}

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
# User Endpoints (Admin Only)
# ------------------------
def admin_required(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admins only")
    return user

@app.get("/users", response_class=APIResponse)
async def list_users(user=Depends(admin_required)):
    trace_id = user["trace_id"]
    print(f"[TRACE {trace_id}] list_users called by {user['id']}")
    query = users.select()
    results = await database.fetch_all(query)
    return APIResponse(success=True, data=[dict(row) for row in results])

@app.get("/users/{user_id}", response_class=APIResponse)
async def get_user(user_id: str, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    print(f"[TRACE {trace_id}] get_user({user_id}) called by {user['id']}")
    query = users.select().where(users.c.id == user_id)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse(success=True, data=dict(record))

@app.post("/users", response_class=APIResponse)
async def create_user(user_data: UserCreate, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    print(f"[TRACE {trace_id}] create_user called by {user['id']}")
    user_id = str(uuid.uuid4())
    query = users.insert().values(id=user_id, name=user_data.name, email=user_data.email)
    await database.execute(query)

    try:
        await publish_event("user.created", {"id": user_id, "name": user_data.name, "email": user_data.email})
    except Exception as e:
        print(f"[Warning] Failed to publish user.created: {e}")

    return APIResponse(success=True, data={"id": user_id, **user_data.dict()}, message="User created")

@app.delete("/users/{user_id}", response_class=APIResponse)
async def delete_user(user_id: str, user=Depends(admin_required)):
    trace_id = user["trace_id"]
    print(f"[TRACE {trace_id}] delete_user({user_id}) called by {user['id']}")
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


# ------------------------
# Internal route for auth-service
# ------------------------
@app.post("/internal/users", response_class=APIResponse)
async def internal_create_user(user_data: UserCreate, request: Request):
    """
    This route is called directly by auth-service (no JWT required).
    It's protected by Docker network isolation (not exposed publicly).
    """
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id

    print(f"[TRACE {trace_id}] internal_create_user called for {user_data.email}")

    # Check if user already exists (prevent duplicates)
    existing_query = users.select().where(users.c.email == user_data.email)
    existing_user = await database.fetch_one(existing_query)
    if existing_user:
        return APIResponse(success=True, data=dict(existing_user), message="User already exists")

    # Create new user record
    user_id = getattr(user_data, "id", None) or str(uuid.uuid4())
    insert_query = users.insert().values(
        id=user_id,
        name=user_data.name,
        email=user_data.email,
        role=getattr(user_data, "role", "user"),
    )
    await database.execute(insert_query)

    # Publish user.created event (optional)
    try:
        await publish_event("user.created", {
            "id": user_id,
            "name": user_data.name,
            "email": user_data.email,
            "role": getattr(user_data, "role", "user"),
        })
    except Exception as e:
        print(f"[Warning] Failed to publish user.created: {e}")

    return APIResponse(success=True, data={"id": user_id, "email": user_data.email}, message="User created internally")
