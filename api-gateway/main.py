from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

app = FastAPI(title="Uber Eats Lite API Gateway", redirect_slashes=False)

# ------------------------
# Logging
# ------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")

# ------------------------
# CORS
# ------------------------
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",
    "*",  # testing only
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# Services
# ------------------------
SERVICES = {
    "users": "http://user-service:8001",
    "orders": "http://order-service:8002",
    "drivers": "http://driver-service:8004",
    "notifications": "http://notification-service:8003",
    "payments": "http://payment-service:8008",
}

# Base paths for services
SERVICE_BASE_PATHS = {
    "users": "users",
    "orders": "",
    "drivers": "",
    "notifications": "",
    "payments": "",
}

# ------------------------
# CORS headers helper
# ------------------------
def make_cors_headers(request: Request):
    origin = request.headers.get("origin", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "true",
    }

# ------------------------
# Health & Root
# ------------------------
@app.get("/health")
def health():
    return {"status": "api-gateway healthy"}

@app.get("/")
def root():
    return {
        "message": "Welcome to Uber Eats Lite API Gateway",
        "available_services": list(SERVICES.keys()),
    }

# ------------------------
# OPTIONS Preflight
# ------------------------
@app.options("/{full_path:path}")
async def preflight(full_path: str, request: Request):
    headers = make_cors_headers(request)
    logger.info(f"Preflight CORS check for {full_path}")
    return Response(status_code=200, headers=headers)

# ------------------------
# Proxy any request
# ------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, service: str, path: str = ""):
    cors_headers = make_cors_headers(request)

    # Handle OPTIONS preflight
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=cors_headers)

    # Validate service
    if service not in SERVICES:
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
            headers=cors_headers,
        )

    # Build target URL
    # Only append path if it's non-empty
    target_url = SERVICES[service]
    if path:
        # Ensure no double slashes
        target_url = f"{target_url.rstrip('/')}/{path.lstrip('/')}"
    elif service == "users":  # special case
        target_url = f"{target_url}/users"

    logger.info(f"Forwarding {request.method} {request.url.path} → {target_url}")

    # Forward the request
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            proxied_response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                content=await request.body(),
            )

        response = Response(
            content=proxied_response.content,
            status_code=proxied_response.status_code,
            media_type=proxied_response.headers.get("content-type", "application/json"),
        )

        # Add CORS headers
        for k, v in cors_headers.items():
            response.headers[k] = v

        return response

    except httpx.ConnectError:
        return Response(
            content=f'{{"error": "{service} service not reachable"}}',
            status_code=503,
            media_type="application/json",
            headers=cors_headers,
        )
