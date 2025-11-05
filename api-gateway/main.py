from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

# ---------------------------------------------------------
# Uber Eats Lite - API Gateway
# ---------------------------------------------------------
app = FastAPI(
    title="Uber Eats Lite API Gateway",
    redirect_slashes=False
)

# ---------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-gateway")

# ---------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Local frontend
    "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",  # ALB
    "*"  # Keep for testing only; restrict later
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
    "users": "http://user-service:8001",
    "orders": "http://order-service:8002",
    "drivers": "http://driver-service:8004",
    "notifications": "http://notification-service:8003",
    "payments": "http://payment-service:8008",
}

# ---------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "api-gateway healthy"}

# ---------------------------------------------------------
# Root Endpoint
# ---------------------------------------------------------
@app.get("/")
def root():
    return {
        "message": "Welcome to Uber Eats Lite API Gateway",
        "available_services": list(SERVICES.keys()),
    }

# ---------------------------------------------------------
# Helper: CORS Headers
# ---------------------------------------------------------
def make_cors_headers(request: Request):
    origin = request.headers.get("origin", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "true",
    }

# ---------------------------------------------------------
# Global OPTIONS Handler (Preflight)
# ---------------------------------------------------------
@app.options("/{full_path:path}")
async def preflight(full_path: str, request: Request):
    headers = make_cors_headers(request)
    logger.info(f"Preflight CORS check for {full_path}")
    return Response(status_code=200, headers=headers)

# ---------------------------------------------------------
# Handle /<service> (root of each service)
# ---------------------------------------------------------
@app.api_route("/{service}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_root(request: Request, service: str):
    return await proxy(request, service, "")

# ---------------------------------------------------------
# Main Proxy Route - /<service>/<path>
# ---------------------------------------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, service: str, path: str = ""):
    cors_headers = make_cors_headers(request)

    # Handle preflight
    if request.method == "OPTIONS":
        logger.info(f"OPTIONS preflight → {service}/{path}")
        return Response(status_code=200, headers=cors_headers)

    # Validate service
    if service not in SERVICES:
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
            headers=cors_headers,
        )

    #  add prefix only if not already present
    target_base = SERVICES[service].rstrip("/")
    if not path or path.startswith(service):
        # path already includes prefix (like /orders/orders)
        target_url = f"{target_base}/{path}".rstrip("/")
    else:
        # add prefix (like /payments/pay)
        target_url = f"{target_base}/{path}".rstrip("/")

    logger.info(f"Proxying {request.method} → {target_url}")

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            proxied_response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                content=await request.body(),
            )

        response = Response(
            content=proxied_response.text,
            status_code=proxied_response.status_code,
            media_type=proxied_response.headers.get("content-type"),
        )

        for k, v in cors_headers.items():
            response.headers[k] = v

        return response

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
