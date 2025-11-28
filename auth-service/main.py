import os
import uuid
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from jose import jwt
from passlib.context import CryptContext
import httpx
from shared.auth import get_optional_user
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Internal
from database import database, engine, metadata
from models import auth_users, Role
from schemas import SignupRequest, LoginRequest

# ---------------------------------------------------------
# Load Config
# ---------------------------------------------------------
load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = "HS256"
JWT_EXP_MINUTES = 60

USER_SERVICE_URL = os.getenv(
    "USER_SERVICE_URL",
    "http://user-service:8001/internal/users"
)
DRIVER_SERVICE_URL = os.getenv(
    "DRIVER_SERVICE_URL",
    "http://driver-service:8004/internal/register"
)

# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("auth-service")

# ---------------------------------------------------------
# Password Hashing
# ---------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
MAX_BCRYPT_BYTES = 72  # bcrypt limit


def hash_password(password: str) -> str:
    """Hash password safely & check 72-byte bcrypt rule."""
    b = password.encode("utf-8")
    if len(b) > MAX_BCRYPT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password too long. Max {MAX_BCRYPT_BYTES} bytes allowed."
        )
    return pwd_context.hash(password)


def verify_password(raw: str, hashed: str) -> bool:
    """Verify password with bcrypt."""
    b = raw.encode("utf-8")
    if len(b) > MAX_BCRYPT_BYTES:
        b = b[:MAX_BCRYPT_BYTES]
        raw = b.decode("utf-8", errors="ignore")
    return pwd_context.verify(raw, hashed)


# ---------------------------------------------------------
# JWT
# ---------------------------------------------------------
def create_jwt(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXP_MINUTES)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------
# FastAPI Setup
# ---------------------------------------------------------
app = FastAPI(title="Auth Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Helper Response
# ---------------------------------------------------------
def api_response(success: bool, data=None, message=None):
    return JSONResponse({
        "success": success,
        "data": data,
        "message": message
    })


# ---------------------------------------------------------
# Helper: Forward request with retries
# ---------------------------------------------------------
async def forward_with_retries(client, method, url, **kwargs):
    retries = 3
    for attempt in range(retries):
        try:
            return await client.request(method, url, **kwargs)
        except httpx.RequestError as e:
            if attempt == retries - 1:
                raise
            wait = 0.25 * (2 ** attempt)
            logging.warning(f"Retrying request ({attempt + 1}/{retries}) in {wait:.1f}s: {e}")
            await asyncio.sleep(wait)


# ---------------------------------------------------------
# Sync Signup → User-Service
# ---------------------------------------------------------
async def sync_user_to_user_service(user_id: str, name: str, email: str, role: str):
    payload = {"id": user_id, "name": name, "email": email, "role": role}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(USER_SERVICE_URL, json=payload)
                if r.status_code in (200, 201):
                    logger.info(f"[UserSync] Synced {email} successfully.")
                    return
                logger.warning(f"[UserSync] Attempt {attempt + 1} failed: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"[UserSync] Error attempt {attempt + 1}: {e}")
        await asyncio.sleep(1.25)
    logger.error(f"[UserSync] FAILED to sync user: {email}")


# ---------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    logger.info("✅ Auth-service started & DB ready.")


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    logger.info("🛑 Auth-service stopped.")


# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "auth-service healthy"}


@app.post("/signup")
async def signup(req: SignupRequest):
    # Validate driver fields before anything
    if req.role == Role.driver:
        if not req.vehicle or not req.license_number:
            raise HTTPException(
                status_code=400,
                detail="Driver must provide vehicle and license_number"
            )

    # Check if email exists
    existing = await database.fetch_one(
        auth_users.select().where(auth_users.c.email == req.email)
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user_id = str(uuid.uuid4())
    try:
        await database.execute(
            auth_users.insert().values(
                id=user_id,
                email=req.email,
                password_hash=hash_password(req.password),
                role=req.role.value
            )
        )
        logger.info(f"[Auth] Created new user: {req.email}")
    except Exception as e:
        logger.error(f"[Auth] Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

    # If driver, register driver record
    if req.role == Role.driver:
        driver_payload = {
            "name": req.name,
            "vehicle": req.vehicle,
            "license_number": req.license_number
        }
        driver_url = f"{DRIVER_SERVICE_URL}?id={user_id}"  # <<--- Pass the same ID
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await forward_with_retries(client, "POST", driver_url, json=driver_payload)
                if resp.status_code >= 400:
                    # Rollback user creation
                    await database.execute(auth_users.delete().where(auth_users.c.id == user_id))
                    logger.error(f"[DriverService] Failed to create driver: {resp.status_code} {resp.text}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Driver creation failed: {resp.text}"
                    )
        except Exception as e:
            await database.execute(auth_users.delete().where(auth_users.c.id == user_id))
            logger.error(f"[DriverService] Exception creating driver: {e}")
            raise HTTPException(
                status_code=500,
                detail="Driver creation failed, user signup rolled back"
            )

    # Return JWT
    token = create_jwt(user_id, req.role.value)
    return api_response(True, {"token": token, "role": req.role.value}, "Signup successful")


@app.post("/login")
async def login(req: LoginRequest):
    user = await database.fetch_one(
        auth_users.select().where(auth_users.c.email == req.email)
    )
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt(user["id"], user["role"])
    logger.info(f"[Auth] User logged in: {req.email} ({user['role']})")
    return api_response(True, {"token": token, "role": user["role"]}, "Login successful")
