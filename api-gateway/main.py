import httpx
import socket

@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(service: str, path: str, request: Request):
    path = path.rstrip("/")

    if request.method == "OPTIONS":
        return Response(status_code=200, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        })

    if service not in SERVICES:
        return Response(
            content=f'{{"error": "Unknown service {service}"}}',
            status_code=404,
            media_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    target_url = f"{SERVICES[service]}/{path}" if path else SERVICES[service]

    # Force IPv4 + disable keep-alive DNS caching issues
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    transport = httpx.AsyncHTTPTransport(retries=2)

    async with httpx.AsyncClient(verify=False, limits=limits, transport=transport) as client:
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
        except httpx.ConnectError as e:
            return Response(
                content=f'{{"error": "{service} service is not reachable", "details": "{str(e)}"}}',
                status_code=503,
                media_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
        except Exception as e:
            return Response(
                content=f'{{"error": "Unexpected error", "details": "{str(e)}"}}',
                status_code=500,
                media_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )
