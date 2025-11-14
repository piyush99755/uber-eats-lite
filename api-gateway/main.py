import os
import uuid
import json
import asyncio
import logging
from jose import jwt, JWTError
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx

# --------------------------------------------------
# App setup
# --------------------------------------------------
app = FastAPI(title="Uber Eats Lite API Gateway", redirect_slashes=False)

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("api-gateway")

# --------------------------------------------------
# CORS
# --------------------------------------------------
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",
    "*",  # dev only
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Config
# --------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = "HS256"

SERVICES = {
    "auth": "http://auth-service:8005",
    "users": "http://user-service:8001",
    "orders": "http://order-service:8002",
    "notifications": "http://notification-service:8003",
    "drivers": "http://driver-service:8004",
    "payments": "http://payment-service:8008",
}

# Services that require JWT authentication
PROTECTED_SERVICES = {"orders", "drivers", "payments"}

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def make_cors_headers(request: Request):
    origin = request.headers.get("origin", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "true",
    }


def decode_jwt(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


async def forward_with_retries(client, **kwargs):
    retries = 3
    for attempt in range(retries):
        try:
            return await client.request(**kwargs)
        except httpx.RequestError as e:
            if attempt == retries - 1:
                raise
            wait = 0.25 * (2 ** attempt)
            logger.warning(f"Retrying request ({attempt + 1}/{retries}) in {wait:.1f}s: {e}")
            await asyncio.sleep(wait)

# --------------------------------------------------
# Middleware for trace_id
# --------------------------------------------------
@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    logger.info(f"[TRACE {trace_id}] {request.method} {request.url.path}")
    return response

# --------------------------------------------------
# Health check
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "api-gateway healthy"}


@app.get("/")
def root():
    return {
        "message": "Welcome to Uber Eats Lite API Gateway",
        "available_services": list(SERVICES.keys()),
    }

# --------------------------------------------------
# Auth routes (handled directly)
# --------------------------------------------------
@app.post("/signup")
async def signup(request: Request):
    """Forward signup to Auth Service."""
    data = await request.json()
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{SERVICES['auth']}/signup", json=data)
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type", "application/json"),
            )
        except Exception as e:
            logger.error(f"Signup failed: {e}")
            return Response(
                content=json.dumps({"success": False, "message": "Auth service unavailable"}),
                status_code=503,
                media_type="application/json",
            )


@app.post("/login")
async def login(request: Request):
    """Forward login to Auth Service."""
    data = await request.json()
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{SERVICES['auth']}/login", json=data)
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type", "application/json"),
            )
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return Response(
                content=json.dumps({"success": False, "message": "Auth service unavailable"}),
                status_code=503,
                media_type="application/json",
            )

# --------------------------------------------------
# OPTIONS Preflight
# --------------------------------------------------
@app.options("/{full_path:path}")
async def preflight(full_path: str, request: Request):
    headers = make_cors_headers(request)
    logger.info(f"Preflight CORS check for {full_path}")
    return Response(status_code=200, headers=headers)

# --------------------------------------------------
# Main proxy route
# --------------------------------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, service: str, path: str = ""):
    cors_headers = make_cors_headers(request)

    # Handle OPTIONS early
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=cors_headers)

    if service not in SERVICES:
        return Response(
            content=json.dumps({"error": f"Unknown service '{service}'"}),
            status_code=404,
            media_type="application/json",
            headers=cors_headers,
        )

    # --------------------------------------------------
    # JWT verification (for protected routes)
    # --------------------------------------------------
    auth_header = request.headers.get("authorization")
    user_claims = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        user_claims = decode_jwt(token)

    if service in PROTECTED_SERVICES and not user_claims:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
            headers=cors_headers,
        )

    # --------------------------------------------------
    # Target URL
    # --------------------------------------------------
    target_url = SERVICES[service]
    if path:
        target_url = f"{target_url.rstrip('/')}/{path.lstrip('/')}"

    # --------------------------------------------------
    # Forward headers
    # --------------------------------------------------
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    headers["x-trace-id"] = request.state.trace_id
    if user_claims:
        headers["x-user-id"] = user_claims.get("sub", "")
        headers["x-user-role"] = user_claims.get("role", "")

    logger.info(f"→ Forwarding {request.method} {request.url.path} → {target_url}")

    # --------------------------------------------------
    # Forward the request
    # --------------------------------------------------
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            proxied_response = await forward_with_retries(
                client,
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(),
            )

        response = Response(
            content=proxied_response.content,
            status_code=proxied_response.status_code,
            media_type=proxied_response.headers.get("content-type", "application/json"),
        )
        for k, v in cors_headers.items():
            response.headers[k] = v
        return response

    except httpx.ConnectError:
        return Response(
            content=json.dumps({"error": f"{service} service not reachable"}),
            status_code=503,
            media_type="application/json",
            headers=cors_headers,
        )

    except Exception as e:
        logger.exception(f"Error proxying {service}: {e}")
        return Response(
            content=json.dumps({"error": "Internal gateway error"}),
            status_code=500,
            media_type="application/json",
            headers=cors_headers,
        )
