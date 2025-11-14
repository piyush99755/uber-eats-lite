import os
import uuid
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
import httpx


# Internal imports
from database import database, engine, metadata
from models import auth_users
from schemas import SignupRequest, LoginRequest

# --------------------------------------------------
# Config
# --------------------------------------------------
load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = "HS256"
JWT_EXP_MINUTES = 60
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001/internal/users")

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("auth-service")

# --------------------------------------------------
# Password Hashing
# --------------------------------------------------


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
MAX_BCRYPT_PASSWORD_BYTES = 72  # bcrypt limitation

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt, ensuring it does not exceed 72 bytes.
    Raises HTTPException if too long.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        # Option 1: Reject long passwords
        raise HTTPException(
            status_code=400,
            detail=f"Password too long. Maximum {MAX_BCRYPT_PASSWORD_BYTES} bytes allowed."
        )
        # Option 2 (alternative): Truncate silently instead of raising
        # password_bytes = password_bytes[:MAX_BCRYPT_PASSWORD_BYTES]
        # password = password_bytes.decode("utf-8", errors="ignore")
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        # truncate silently to compare correctly
        password_bytes = password_bytes[:MAX_BCRYPT_PASSWORD_BYTES]
        password = password_bytes.decode("utf-8", errors="ignore")
    return pwd_context.verify(password, hashed)

# --------------------------------------------------
# JWT Handling
# --------------------------------------------------
def create_jwt(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXP_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# --------------------------------------------------
# FastAPI Setup
# --------------------------------------------------
app = FastAPI(title="Auth Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def api_response(success: bool, data=None, message=None):
    return JSONResponse({"success": success, "data": data, "message": message})

async def create_user_in_user_service(user_id: str, name: str, email: str, role: str):
    """Send user creation request to user-service asynchronously."""
    payload = {"id": user_id, "name": name, "email": email, "role": role}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(USER_SERVICE_URL, json=payload)
                if resp.status_code in (200, 201):
                    logger.info(f"[UserSync] {email} created in user-service.")
                    return
                else:
                    logger.warning(f"[UserSync] Attempt {attempt+1} failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"[UserSync] Attempt {attempt+1} error: {e}")
        await asyncio.sleep(1.5)
    logger.error(f"[UserSync] Failed to create user {email} after retries.")

# --------------------------------------------------
# Lifecycle
# --------------------------------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    logger.info("✅ Auth service started and DB connected.")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    logger.info("🛑 Auth service stopped.")

# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "auth-service healthy"}

@app.post("/signup")
async def signup(req: SignupRequest):
    # Check for existing user
    query = auth_users.select().where(auth_users.c.email == req.email)
    existing = await database.fetch_one(query)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create new user in auth DB
    user_id = str(uuid.uuid4())
    insert_query = auth_users.insert().values(
        id=user_id,
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    await database.execute(insert_query)
    logger.info(f"[Auth] New user created: {req.email}")

    # Also sync to user-service (async)
    asyncio.create_task(create_user_in_user_service(user_id, req.name, req.email, req.role))

    # Create JWT
    token = create_jwt(user_id, req.role)
    return api_response(True, {"token": token, "role": req.role}, "User created successfully")

@app.post("/login")
async def login(req: LoginRequest):
    query = auth_users.select().where(auth_users.c.email == req.email)
    user = await database.fetch_one(query)

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt(user["id"], user["role"])
    return api_response(True, {"token": token, "role": user["role"]}, "Login successful")
