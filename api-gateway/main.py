from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

# ---------------------------------------------------------
# API Gateway for Uber Eats Lite
# ---------------------------------------------------------
app = FastAPI(
    title="API Gateway",
    redirect_slashes=False  # Prevents redirect loops like 307
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
    "*"  # Keep this for testing; remove in production
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
# Proxy Route — Forwards requests to internal services
# ---------------------------------------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(service: str, path: str, request: Request):
    """
    Generic route that proxies requests to the correct internal service.
    Example: /users/health → user-service
    """

    # Normalize path
    path = path.rstrip("/")

    # Validate service
    if service not in SERVICES:
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
        )

    # Remove duplicate prefix if present (like /users/users)
    if path.startswith(service + "/"):
        path = path[len(service) + 1:]

    target_url = f"{SERVICES[service]}/{path}" if path else SERVICES[service]
    logger.info(f"Proxying {request.method} → {target_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                content=await request.body(),
            )

        return Response(
            content=response.text,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )

    except httpx.ConnectError:
        logger.error(f"Service {service} unreachable at {target_url}")
        return Response(
            content=f'{{"error": "{service} service is not reachable"}}',
            status_code=503,
            media_type="application/json",
        )

    except Exception as e:
        logger.exception("Unexpected error in proxy")
        return Response(
            content=f'{{"error": "Unexpected error: {str(e)}"}}',
            status_code=500,
            media_type="application/json",
        )
