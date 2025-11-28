import os
import uuid
import json
import asyncio
import logging
from jose import jwt, JWTError
from fastapi import FastAPI, Request, Response, Query,WebSocket, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from shared.auth import get_optional_user
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
# --------------------------------------------------
# Demo admin user for portfolio/demo purposes
# --------------------------------------------------
DEMO_ADMIN = {
    "email": "admin@demo.com",
    "password": "admin123",
    "role": "admin",
    "id": "00000000-0000-0000-0000-000000000000"
}

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
    Login endpoint supporting:
    1. Demo admin account
    2. Normal users via auth-service
    3. Drivers with driver info attached
    """
    data = await request.json()
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())

    # -------------------------
    # 1️⃣ Check for demo admin
    # -------------------------
    if data.get("email") == DEMO_ADMIN["email"] and data.get("password") == DEMO_ADMIN["password"]:
        from datetime import datetime, timedelta

        token = jwt.encode(
            {
                "sub": DEMO_ADMIN["id"],
                "role": DEMO_ADMIN["role"],
                "exp": datetime.utcnow() + timedelta(hours=2),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM
        )

        logger.info(f"[TRACE {trace_id}] Demo admin logged in: {DEMO_ADMIN['id']}")
        return Response(
            content=json.dumps({
                "success": True,
                "data": {
                    "token": token,
                    "role": DEMO_ADMIN["role"],
                    "email": DEMO_ADMIN["email"]
                },
                "message": "Login successful (demo admin)"
            }),
            status_code=200,
            media_type="application/json",
            headers={"x-trace-id": trace_id},
        )

    # -------------------------
    # 2️⃣ Forward login to auth-service
    # -------------------------
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

    # -------------------------
    # 3️⃣ Propagate auth-service error
    # -------------------------
    if auth_resp.status_code >= 400:
        return Response(
            content=auth_resp.content,
            status_code=auth_resp.status_code,
            media_type=auth_resp.headers.get("content-type", "application/json"),
        )

    # -------------------------
    # 4️⃣ Parse auth response
    # -------------------------
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

    # -------------------------
    # 5️⃣ If driver, fetch driver record
    # -------------------------
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

    # -------------------------
    # 6️⃣ Build final response
    # -------------------------
    final_data = auth_data.get("data", {})
    if driver_info:
        final_data["driver"] = driver_info

    return Response(
        content=json.dumps({"success": True, "data": final_data, "message": "Login successful"}),
        status_code=200,
        media_type="application/json",
        headers={"x-trace-id": trace_id},
    )

    
    
async def proxy_request(service_name: str, path: str, request: Request):
    service_url = SERVICES.get(service_name)
    if not service_url:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    target_url = f"{service_url.rstrip('/')}/{path.lstrip('/')}"
    method = request.method
    # forward headers but remove Host (httpx will set its own)
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    # keep trace id if present or set a new one
    headers.setdefault("x-trace-id", request.state.trace_id)
    body = await request.body()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        proxied_response = await client.request(method, target_url, headers=headers, content=body)

    # Build Response: include content-type and other safe headers
    media_type = proxied_response.headers.get("content-type")
    response = Response(content=proxied_response.content,
                        status_code=proxied_response.status_code,
                        media_type=media_type)

    # copy a small useful set of headers (avoid hop-by-hop headers)
    for k, v in proxied_response.headers.items():
        lower_k = k.lower()
        if lower_k in {"content-type", "content-length", "etag", "cache-control", "x-trace-id"}:
            response.headers[k] = v

    return response

# --------------------------------------------------
# DRIVER ROUTES (Production Ready)
# --------------------------------------------------
@app.get("/drivers/me")
async def driver_me(request: Request):
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header.split(" ")[1]
    user = decode_jwt(token)

    if not user or user.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Driver privileges required")

    driver_id = user.get("sub")

    return await proxy_request(
        "drivers",
        f"drivers/{driver_id}",    
        request
    )


@app.get("/drivers/deliveries/history")
async def driver_deliveries_history(request: Request):
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header.split(" ")[1]
    user = decode_jwt(token)

    if not user or user.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Driver privileges required")

    driver_id = user.get("sub")

    return await proxy_request(
        "drivers",
        f"drivers/{driver_id}/deliveries/history",  
        request
    )
    
#fetching all drivers for admin role..
@app.get("/drivers/all")
async def admin_get_all_drivers(request: Request):
    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header.split(" ")[1]
    user = decode_jwt(token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    return await proxy_request("drivers", "drivers", request)  # your driver-service should return all drivers at /drivers

@app.post("/drivers/internal/register")
async def proxy_internal_register(request: Request):
    return await proxy_request("drivers", "internal/register", request)


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

        # Admin can access everything
        if role == "admin":
            pass  # skip all role checks

        # Driver-specific check
        elif service == "drivers" and role != "driver":
            return Response(
                content=json.dumps({"error": "Driver privileges required"}),
                status_code=403,
                media_type="application/json",
                headers=cors_headers,
            )

        # User-specific check
        elif service == "users" and role != "user":
            return Response(
                content=json.dumps({"error": "User privileges required"}),
                status_code=403,
                media_type="application/json",
                headers=cors_headers,
            )

       

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
    token = websocket.query_params.get("token")
    
    # --- Validate token ---
    if not token:
        await websocket.close(code=4001)
        return

    user_claims = decode_jwt(token)
    if not user_claims:
        await websocket.close(code=4002)
        return

    await websocket.accept()

    # SSE source endpoint
    sse_url = f"{SERVICES['orders']}/orders/orders/events/stream?token={token}"

    headers = {
        "Accept": "text/event-stream",
        "x-trace-id": str(uuid.uuid4())
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", sse_url, headers=headers) as sse_response:

                buffer = ""

                async for chunk in sse_response.aiter_text():
                    buffer += chunk

                    # Process each SSE event in the buffer
                    while "\n\n" in buffer:
                        raw_event, buffer = buffer.split("\n\n", 1)

                        for line in raw_event.splitlines():
                            if not line.startswith("data:"):
                                continue

                            data_str = line[len("data:"):].strip()

                            try:
                                event_json = json.loads(data_str)
                                await websocket.send_json(event_json)

                            except Exception as ws_err:
                                logger.error(f"Failed to send event to WS: {ws_err}")
                                await websocket.close(code=4003)
                                return

    except Exception as e:
        logger.error(f"SSE proxy error: {e}")

    finally:
        try:
            await websocket.close()
        except:
            pass
