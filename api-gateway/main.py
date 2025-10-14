# main.py
from fastapi import FastAPI, Request
import httpx

app = FastAPI(title="API Gateway")

# Map each service name to its local URL
SERVICES = {
    "users": "http://127.0.0.1:8001",
    "orders": "http://127.0.0.1:8002",
    "drivers": "http://127.0.0.1:8004",
    "notifications": "http://127.0.0.1:8003",
    "payments": "http://127.0.0.1:8008",
}

@app.get("/")
def root():
    return {"message": "Welcome to API Gateway", "available_routes": list(SERVICES.keys())}

@app.get("/health")
def health():
    return {"status": "api-gateway healthy"}

# Generic proxy route — handles GET, POST, PUT, DELETE for all services
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    if service not in SERVICES:
        return {"error": f"Unknown service '{service}'"}

    target_url = f"{SERVICES[service]}/{path}" if path else f"{SERVICES[service]}/{service}"

    method = request.method
    headers = dict(request.headers)
    body = await request.body()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method,
                target_url,
                headers=headers,
                content=body,
            )
            return response.json()
        except httpx.ConnectError:
            return {"error": f"{service} service is not reachable"}
        except Exception as e:
            return {"error": str(e)}

