# driver-service/ws_manager.py
import asyncio
import logging
import json
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("driver-service.ws")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)

# Keep track of connected clients
connected_clients: Set[WebSocket] = set()
clients_lock = asyncio.Lock()


async def connect_client(ws: WebSocket):
    """
    Accept a new WebSocket connection and add it to the clients set
    """
    await ws.accept()
    async with clients_lock:
        connected_clients.add(ws)
    logger.info(f"[WS CONNECT] Client connected. Total clients: {len(connected_clients)}")


async def disconnect_client(ws: WebSocket):
    """
    Remove WebSocket client from the clients set
    """
    async with clients_lock:
        connected_clients.discard(ws)
    logger.info(f"[WS DISCONNECT] Client disconnected. Total clients: {len(connected_clients)}")


async def broadcast_to_connected_clients(event_type: str, data: dict):
    """
    Send an event to all connected WebSocket clients.
    Does not raise on errors per client; removes dead connections.
    """
    message = json.dumps({"type": event_type, "data": data})
    disconnected = []

    async with clients_lock:
        for ws in connected_clients:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"[WS BROADCAST ERROR] Removing client: {e}")
                disconnected.append(ws)

        # Clean up disconnected clients
        for ws in disconnected:
            connected_clients.discard(ws)

    if disconnected:
        logger.info(f"[WS BROADCAST] Removed {len(disconnected)} disconnected clients")
    logger.info(f"[WS BROADCAST] Event '{event_type}' sent to {len(connected_clients)} clients")
