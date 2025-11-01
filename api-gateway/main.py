from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

# ---------------------------------------------------------
# API Gateway for Uber Eats Lite
# ---------------------------------------------------------
app = FastAPI(
    title="API Gateway",
    redirect_slashes=False
)

# ---------------------------------------------------------
# Logging setup
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")

# ---------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Local frontend
    "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",  # ALB
    "*"  # Keep * for testing; restrict in production
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Service Routing Table
# ---------------------------------------------------------
SERVICES = {
    "users": "http://user-service-uber.uber-eats-lite.local:8001",
    "orders": "http://order-service-uber.uber-eats-lite.local:8002",
    "drivers": "http://driver-service-uber.uber-eats-lite.local:8004",
    "notifications": "http://notification-service-uber.uber-eats-lite.local:8003",
    "payments": "http://payment-service-uber.uber-eats-lite.local:8008",
}

# ---------------------------------------------------------
# Health Endpoint
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}

# ---------------------------------------------------------
# Root Endpoint
# ---------------------------------------------------------
@app.get("/")
def root():
    return {
        "message": "Welcome to the API Gateway",
        "available_services": list(SERVICES.keys()),
    }

# ---------------------------------------------------------
# Global OPTIONS Handler (Preflight)
# ---------------------------------------------------------
@app.options("/{full_path:path}")
async def preflight(full_path: str, request: Request):
    origin = request.headers.get("origin", "*")
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "true",
    }
    logger.info(f"Preflight CORS check for {full_path}")
    return Response(status_code=200, headers=headers)

# ---------------------------------------------------------
# Proxy Route — Forwards requests to internal services
# ---------------------------------------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(service: str, path: str, request: Request):
    """
    Generic route that proxies requests to internal microservices.

    Example:
      /users/health  → http://user-service-uber.uber-eats-lite.local:8001/health
      /orders/create → http://order-service-uber.uber-eats-lite.local:8002/create
    """

    # Dynamic CORS headers
    origin = request.headers.get("origin", "*")
    cors_headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "true",
    }

    # Handle preflight immediately
    if request.method == "OPTIONS":
        logger.info(f"OPTIONS preflight → {service}/{path}")
        return Response(status_code=200, headers=cors_headers)

    # Validate service
    if service not in SERVICES:
        logger.warning(f"Unknown service requested: {service}")
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
            headers=cors_headers,
        )

    # Normalize redundant prefixes
    if path.startswith(service + "/"):
        path = path[len(service) + 1:]
    elif path == service:
        path = ""

    target_url = f"{SERVICES[service]}/{path}" if path else SERVICES[service]
    logger.info(f"Proxying {request.method} → {target_url}")

    try:
        async with httpx.AsyncClient() as client:
            proxied_response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                content=await request.body(),
            )

        # Return proxied response with CORS headers
        return Response(
            content=proxied_response.text,
            status_code=proxied_response.status_code,
            media_type=proxied_response.headers.get("content-type"),
            headers={**cors_headers},
        )

    except httpx.ConnectError:
        logger.error(f"{service} unreachable at {target_url}")
        return Response(
            content=f'{{"error": "{service} service not reachable"}}',
            status_code=503,
            media_type="application/json",
            headers=cors_headers,
        )

    except Exception as e:
        logger.exception("Unexpected error in proxy")
        return Response(
            content=f'{{"error": "Unexpected error: {str(e)}"}}',
            status_code=500,
            media_type="application/json",
            headers=cors_headers,
        )
