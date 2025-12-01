# order-service/ws_manager.py
import logging
from typing import List
from fastapi import WebSocket

logger = logging.getLogger("ws_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS] Client connected ({len(self.active_connections)} active)")

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        logger.info(f"[WS] Client disconnected ({len(self.active_connections)} active)")

    async def broadcast(self, message: dict):
        """Send JSON message to all connected WS clients."""
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        # Disconnect failed sockets
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()
