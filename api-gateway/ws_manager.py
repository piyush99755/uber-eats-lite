import asyncio
import json
import websockets
from fastapi import WebSocket

BACKENDS = {
    "orders": "ws://order-service:8002/ws/orders",
    "drivers": "ws://driver-service:8004/ws/drivers",
    "payments": "ws://payment-service:8008/ws/payments",
}

class MultiBackendWS:
    def __init__(self):
        self.backend_tasks = []
        self.backend_connections = {}

    async def connect_to_backend(self, name: str, url: str, client_ws: WebSocket):
        """Connects to 1 backend and streams messages → client."""
        while True:
            try:
                async with websockets.connect(url) as backend:
                    print(f"[WS-MULTI] Connected → {name}")

                    self.backend_connections[name] = backend

                    async for msg in backend:
                        await client_ws.send_text(msg)

            except Exception as e:
                print(f"[WS-MULTI] Lost {name}, retrying in 2s: {e}")
                await asyncio.sleep(2)

    async def start(self, client_ws: WebSocket):
        """Start streaming from all backend WebSockets."""
        self.backend_tasks = [
            asyncio.create_task(self.connect_to_backend(name, url, client_ws))
            for name, url in BACKENDS.items()
        ]

    async def stop(self):
        for t in self.backend_tasks:
            t.cancel()
