# sse_clients.py
from typing import List
import asyncio

clients: List[asyncio.Queue] = []
