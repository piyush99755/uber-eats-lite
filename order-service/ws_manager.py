# ws_manager.py
import asyncio
from typing import List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_event(self, websocket: WebSocket, event: dict):
        await websocket.send_json(event)

    async def broadcast(self, event: dict):
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(event)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()
