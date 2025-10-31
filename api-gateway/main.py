from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx

# ---------------------------------------------------------
# API Gateway for Uber Eats Lite
# ---------------------------------------------------------
app = FastAPI(
    title="API Gateway",
    redirect_slashes=False  # Prevents FastAPI 307 redirects that break CORS preflight
)

# ---------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Local frontend
        "http://uber-eats-lite-alb-849444077.us-east-1.elb.amazonaws.com",  # ALB
        "*"  # For testing; remove in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Global OPTIONS handler — handles all CORS preflights
# ---------------------------------------------------------
@app.options("/{full_path:path}")
async def preflight(full_path: str):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }
    return Response(status_code=200, headers=headers)

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
    # Normalize trailing slash (avoid redirect)
    path = path.rstrip("/")

    # Handle preflight requests directly
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
        return Response(status_code=200, headers=headers)

    # Validate service name
    if service not in SERVICES:
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # Build target service URL
    target_url = f"{SERVICES[service]}/{path}" if path else SERVICES[service]

    # Proxy request
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                content=await request.body(),
            )

            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }

            return Response(
                content=response.text,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
                headers=headers,
            )

        except httpx.ConnectError:
            return Response(
                content=f'{{"error": "{service} service is not reachable"}}',
                status_code=503,
                media_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        except Exception as e:
            return Response(
                content=f'{{"error": "Unexpected error: {str(e)}"}}',
                status_code=500,
                media_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
