import os
import uuid
import json
import asyncio
import logging
from jose import jwt, JWTError
from fastapi import FastAPI, Request, Response, Query,WebSocket, Depends
from fastapi.responses import StreamingResponse
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
    # Ensure we always set trace id on response
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
    """
    Handle user signup. If role == 'driver', also create a driver record.
    """

    data = await request.json()
    role = data.get("role", "user")

    # -------------------------
    # Prepare payloads
    # -------------------------
    auth_payload = {
        "name": data.get("name"),
        "email": data.get("email"),
        "password": data.get("password"),
        "role": role
    }

    # driver-specific fields
    vehicle = data.get("vehicle")
    license_number = data.get("license_number")

    # -------------------------
    # 1️⃣ Create user in auth-service
    # -------------------------
    try:
        async with httpx.AsyncClient() as client:
            auth_resp = await forward_with_retries(
                client,
                method="POST",
                url=f"{SERVICES['auth']}/signup",
                json=auth_payload
            )
    except Exception as e:
        logger.error(f"Signup failed (auth): {e}")
        return Response(
            content=json.dumps({"success": False, "message": "Auth service unavailable"}),
            status_code=503,
            media_type="application/json"
        )

    # propagate auth errors
    if auth_resp.status_code >= 400:
        return Response(
            content=auth_resp.content,
            status_code=auth_resp.status_code,
            media_type=auth_resp.headers.get("content-type", "application/json")
        )

    # parse auth response
    try:
        auth_data = auth_resp.json()
    except Exception:
        auth_data = {}

    user_id = auth_data.get("user_id") or auth_data.get("id")
    token = auth_data.get("token") or auth_data.get("access_token")

    # decode token if needed
    if not user_id and token:
        decoded = decode_jwt(token)
        if decoded:
            user_id = decoded.get("sub")

    # -------------------------
    # 2️⃣ Create driver record if role=driver
    # -------------------------
    if role == "driver":
        # ensure required driver fields
        if not vehicle or not license_number:
            return Response(
                content=json.dumps({"success": False, "message": "Missing driver fields (vehicle, license_number)"}),
                status_code=400,
                media_type="application/json"
            )

        driver_payload = {
            "id": user_id or str(uuid.uuid4()),  # keep 1:1 mapping
            "name": data.get("name"),
            "vehicle": vehicle,
            "license_number": license_number,
            "status": "available"
        }

        try:
            async with httpx.AsyncClient() as client:
                driver_resp = await forward_with_retries(
                    client,
                    method="POST",
                    url=f"{SERVICES['drivers'].rstrip('/')}/drivers",
                    json=driver_payload,
                    headers={"x-trace-id": request.state.trace_id}
                )
        except Exception as e:
            logger.error(f"Driver creation failed: {e}")
            return Response(
                content=json.dumps({
                    "success": True,
                    "warning": "User created but driver record creation failed. Please contact admin.",
                    "auth_response": auth_data
                }),
                status_code=207,
                media_type="application/json"
            )

        if driver_resp.status_code >= 400:
            logger.error(f"Driver-service returned error: {driver_resp.status_code} {driver_resp.text}")
            driver_resp_content = driver_resp.json() if driver_resp.headers.get("content-type", "").startswith("application/json") else driver_resp.text
            return Response(
                content=json.dumps({
                    "success": True,
                    "warning": "User created but driver record creation failed.",
                    "auth_response": auth_data,
                    "driver_response": driver_resp_content
                }),
                status_code=207,
                media_type="application/json"
            )

    # -------------------------
    # 3️⃣ Success: return auth response
    # -------------------------
    return Response(
        content=auth_resp.content,
        status_code=auth_resp.status_code,
        media_type=auth_resp.headers.get("content-type", "application/json")
    )



@app.post("/login")
async def login(request: Request):
    """
    Forward login request to auth-service. If user is a driver,
    fetch driver record from driver-service and include it in the response.
    """
    data = await request.json()
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())

    # 1️⃣ Forward login to auth-service
    async with httpx.AsyncClient() as client:
        try:
            auth_resp = await client.post(
                f"{SERVICES['auth']}/login",
                json=data,
                headers={"x-trace-id": trace_id}
            )
        except Exception as e:
            logger.error(f"Login failed (auth-service): {e}")
            return Response(
                content=json.dumps({"success": False, "message": "Auth service unavailable"}),
                status_code=503,
                media_type="application/json",
            )

    # 2️⃣ Propagate auth-service error
    if auth_resp.status_code >= 400:
        return Response(
            content=auth_resp.content,
            status_code=auth_resp.status_code,
            media_type=auth_resp.headers.get("content-type", "application/json"),
        )

    # 3️⃣ Parse auth response
    try:
        auth_data = auth_resp.json()
        token = auth_data.get("data", {}).get("token")
        role = auth_data.get("data", {}).get("role")
        user_id = None
        if token:
            decoded = decode_jwt(token)
            if decoded:
                user_id = decoded.get("sub")
                logger.info(f"[TRACE {trace_id}] User logged in: {user_id} ({decoded.get('role')})")
    except Exception:
        token = None
        role = None
        user_id = None

    # 4️⃣ If driver, fetch driver record
    driver_info = None
    if role == "driver" and user_id:
        try:
            async with httpx.AsyncClient() as client:
                driver_resp = await client.get(
                    f"{SERVICES['drivers'].rstrip('/')}/drivers/{user_id}",
                    headers={"x-trace-id": trace_id}
                )
                if driver_resp.status_code == 200:
                    driver_info = driver_resp.json()
                else:
                    logger.warning(f"Driver service returned {driver_resp.status_code} for driver {user_id}")
        except Exception as e:
            logger.error(f"Failed to fetch driver info: {e}")

    # 5️⃣ Build final response
    final_data = auth_data.get("data", {})
    if driver_info:
        final_data["driver"] = driver_info

    return Response(
        content=json.dumps({"success": True, "data": final_data, "message": "Login successful"}),
        status_code=200,
        media_type="application/json",
        headers={"x-trace-id": trace_id},
    )

# --------------------------------------------------
# Main proxy route
# --------------------------------------------------
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, service: str, path: str = ""):
    cors_headers = make_cors_headers(request)

    # Handle CORS preflight
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=cors_headers)

    if service not in SERVICES:
        return Response(
            content=json.dumps({"error": f"Unknown service '{service}'"}),
            status_code=404,
            media_type="application/json",
            headers=cors_headers,
        )

    # Extract JWT
    auth_header = request.headers.get("authorization")
    user_claims = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ")[1]
        user_claims = decode_jwt(token)

    # Check protected services
    if service in PROTECTED_SERVICES and not user_claims:
        return Response(
            content=json.dumps({"error": "Unauthorized"}),
            status_code=401,
            media_type="application/json",
            headers=cors_headers,
        )

    # Role-based rules
    if user_claims:
        role = user_claims.get("role")
        user_id = user_claims.get("sub")

        if service == "drivers" and role != "driver":
            return Response(
                content=json.dumps({"error": "Driver privileges required"}),
                status_code=403,
                media_type="application/json",
                headers=cors_headers,
            )

        if service == "users" and role != "user":
            return Response(
                content=json.dumps({"error": "User privileges required"}),
                status_code=403,
                media_type="application/json",
                headers=cors_headers,
            )

        # Only rewrite /drivers/me → /drivers/<driver_id>
        if service == "drivers" and path == "me" and role == "driver":
            path = f"drivers/{user_id}"

    # Build target URL
    target_url = f"{SERVICES[service].rstrip('/')}/{path.lstrip('/')}" if path else SERVICES[service]

    # Forward headers
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    if auth_header:
        headers["authorization"] = auth_header
    headers["x-trace-id"] = request.state.trace_id
    if user_claims:
        headers["x-user-id"] = user_claims.get("sub", "")
        headers["x-user-role"] = user_claims.get("role", "")

    logger.info(f"→ Forwarding {request.method} {request.url.path} → {target_url}")

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            proxied_response = await forward_with_retries(
                client,
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(),
            )

        media_type = proxied_response.headers.get("content-type", "application/json")
        response = Response(
            content=proxied_response.content,
            status_code=proxied_response.status_code,
            media_type=media_type,
        )

        for k, v in cors_headers.items():
            response.headers[k] = v
        response.headers["x-trace-id"] = request.state.trace_id

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

@app.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    user_claims = decode_jwt(token)
    if not user_claims:
        await websocket.close(code=4002)
        return

    sse_url = f"{SERVICES['orders']}/orders/orders/events/stream?token={token}"
    headers = {
        "Accept": "text/event-stream",
        "x-trace-id": str(uuid.uuid4()),
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", sse_url, headers=headers) as sse_resp:
                if sse_resp.status_code != 200:
                    await websocket.send_json({"error": "Failed to connect to order service SSE"})
                    await websocket.close()
                    return

                async for line in sse_resp.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            event = json.loads(data_str)
                            await websocket.send_json(event)
                        except Exception as e:
                            logger.error(f"Failed to send event to WebSocket: {e}")
    except Exception as e:
        logger.error(f"SSE proxy error: {e}")
    finally:
        await websocket.close()
