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
import websockets
from typing import Optional

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

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8003")
DRIVER_SERVICE_URL = os.getenv("DRIVER_SERVICE_URL", "http://driver-service:8004")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8008")

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

# ---------- WebSocket relay helpers & endpoints (replace existing relays) ----------


ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8003")
DRIVER_SERVICE_URL = os.getenv("DRIVER_SERVICE_URL", "http://driver-service:8004")

def http_to_ws(url: str) -> str:
    """
    Convert http(s) -> ws(s). If url already ws:// or wss://, return as-is.
    """
    if url.startswith("wss://") or url.startswith("ws://"):
        return url
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    return url

async def _relay_bidirectional(client_ws: WebSocket, backend_ws, client_to_backend_name="c->b", backend_to_client_name="b->c"):
    """
    Relay loop: read backend -> send client, and client -> backend concurrently.
    Expects backend_ws to be an object supporting `send` and `__aiter__` (websockets library).
    """
    async def _backend_to_client():
        try:
            async for msg in backend_ws:
                # backend msg may be bytes or text
                if isinstance(msg, (bytes, bytearray)):
                    await client_ws.send_bytes(msg)
                else:
                    await client_ws.send_text(msg)
                logger.debug(f"[WS RELAY] {backend_to_client_name} forwarded message")
        except Exception as e:
            logger.debug(f"[WS RELAY] {backend_to_client_name} terminated: {e}")
            raise

    async def _client_to_backend():
        try:
            while True:
                # FastAPI WebSocket receive returns text/bytes depending on message type
                data = await client_ws.receive()
                # data is a dict like {"type":"websocket.receive", "text": "..."} or "bytes"
                if "text" in data and data["text"] is not None:
                    await backend_ws.send(data["text"])
                elif "bytes" in data and data["bytes"] is not None:
                    await backend_ws.send(data["bytes"])
                elif data.get("type") == "websocket.disconnect":
                    # client closed connection
                    raise asyncio.CancelledError("client disconnected")
                logger.debug(f"[WS RELAY] {client_to_backend_name} forwarded message")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"[WS RELAY] {client_to_backend_name} terminated: {e}")
            raise

    tasks = [
        asyncio.create_task(_backend_to_client(), name="backend_to_client"),
        asyncio.create_task(_client_to_backend(), name="client_to_backend"),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for t in pending:
        t.cancel()
    # re-raise any exception from done tasks so outer handler can log/handle
    for t in done:
        if t.exception():
            raise t.exception()

async def _relay_loop(
    websocket: WebSocket,
    backend_url: str,
    extra_headers: Optional[list] = None
):
    """
    WebSocket relay loop compatible with very old websockets versions (3.x–4.x).
    Does NOT pass any extra_headers under any circumstances.
    """

    await websocket.accept()
    logger.info(f"[WS-GATEWAY] Client accepted, relaying to backend: {backend_url}")

    backoff = 1.0
    backoff_max = 8.0

    while True:
        try:
            logger.info(f"[WS-GATEWAY] Connecting to backend: {backend_url}")

            # ✔ websockets < 5.0 only accepts ONE argument → the URI
            async with websockets.connect(backend_url) as backend_ws:
                logger.info(f"[WS-GATEWAY] Connected to backend: {backend_url}")

                backoff = 1.0

                # relay until client or backend closes
                await _relay_bidirectional(websocket, backend_ws)

                logger.info("[WS-GATEWAY] Relay ended normally")
                break

        except websockets.InvalidURI as e:
            logger.error(f"[WS-GATEWAY] Invalid backend URI: {e}")
            await websocket.close(code=1011)
            break

        except asyncio.CancelledError:
            logger.info("[WS-GATEWAY] Relay cancelled")
            break

        except Exception as e:
            logger.error(
                f"[WS-GATEWAY] Backend WS error, reconnecting in {backoff:.1f}s → {e}"
            )

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                break

            backoff = min(backoff * 2, backoff_max)
            continue

    # close client socket if open
    try:
        await websocket.close()
    except Exception:
        pass

    logger.info("[WS-GATEWAY] Client connection closed")


# ---------- endpoints using helper ----------
@app.websocket("/ws/orders")
async def orders_relay(websocket: WebSocket):
    await websocket.accept()

    token = websocket.query_params.get("token")

    # -------------------- BACKEND URLS --------------------
    backend_targets = [
        ("order",   http_to_ws(f"{ORDER_SERVICE_URL}/ws/orders")),
        ("driver",  http_to_ws(f"{DRIVER_SERVICE_URL}/ws/drivers")),
        ("payment", http_to_ws(f"{PAYMENT_SERVICE_URL}/ws/payments")),
    ]

    # -------------------- CONNECT WITH RETRY --------------------
    async def connect_with_retry(name, url, max_tries=60, delay=0.5):
        for attempt in range(1, max_tries + 1):
            try:
                ws = await websockets.connect(url)
                logger.info(f"[WS-MULTI] Connected to {name} backend: {url}")
                return ws
            except Exception as e:
                logger.warning(
                    f"[WS-MULTI] {name} not ready ({url}). Retry {attempt}/{max_tries}. Error: {e}"
                )
                await asyncio.sleep(delay)
        logger.error(f"[WS-MULTI] FAILED TO CONNECT to {name}: {url}")
        return None

    # connect to all services
    connections = []
    for name, url in backend_targets:
        ws = await connect_with_retry(name, url)
        if ws:
            connections.append((name, ws))

    # -------------------- BACKEND → CLIENT PUMP --------------------
    async def pump_backend(name: str, conn):
        """
        Reads messages from each backend WS and forwards them to the browser.
        Ensures the message is parsed and flattened so frontend receives:

        {
          "source": "payment",
          "type": "payment.completed",
          "order_id": 123
        }
        """
        try:
            async for msg in conn:
                try:
                    parsed = json.loads(msg)
                except Exception:
                    parsed = {"type": "unknown", "payload": msg}

                parsed["source"] = name
                await websocket.send_text(json.dumps(parsed))

        except Exception as e:
            logger.error(f"[WS-MULTI] Backend pump {name} ended: {e}")

    pump_tasks = [
        asyncio.create_task(pump_backend(name, conn))
        for name, conn in connections
    ]

    # -------------------- CLIENT → BACKEND (broadcast) --------------------
    try:
        while True:
            data = await websocket.receive()

            if data["type"] == "websocket.disconnect":
                break

            if "text" in data and data["text"] is not None:
                payload = data["text"]
            elif "bytes" in data and data["bytes"] is not None:
                payload = data["bytes"]
            else:
                continue

            for _, conn in connections:
                try:
                    await conn.send(payload)
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"[WS-MULTI] Client → backend loop ended: {e}")

    finally:
        # Cleanup backend sockets
        for _, conn in connections:
            try:
                await conn.close()
            except:
                pass

        # Cancel pump tasks
        for t in pump_tasks:
            t.cancel()


@app.websocket("/ws/notifications")
async def notifications_relay(websocket: WebSocket):
    backend_http = f"{NOTIFICATION_SERVICE_URL.rstrip('/')}/ws/notifications"
    backend_ws = http_to_ws(backend_http)
    token = websocket.query_params.get("token")
    extra_headers = []
    if token:
        extra_headers.append(("Authorization", f"Bearer {token}"))
    trace = websocket.query_params.get("trace_id")
    if trace:
        extra_headers.append(("x-trace-id", trace))
    await _relay_loop(websocket, backend_ws, extra_headers=extra_headers)

@app.websocket("/ws/drivers")
async def drivers_relay(websocket: WebSocket):
    backend_http = f"{DRIVER_SERVICE_URL.rstrip('/')}/ws/drivers"
    backend_ws = http_to_ws(backend_http)
    token = websocket.query_params.get("token")
    extra_headers = []
    if token:
        extra_headers.append(("Authorization", f"Bearer {token}"))
    trace = websocket.query_params.get("trace_id")
    if trace:
        extra_headers.append(("x-trace-id", trace))
    await _relay_loop(websocket, backend_ws, extra_headers=extra_headers)
