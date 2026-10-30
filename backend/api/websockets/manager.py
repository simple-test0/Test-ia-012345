import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: Dict[str, List[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[room_id].append(websocket)

    async def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(room_id, [])
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                self._connections.pop(room_id, None)

    async def send(self, room_id: str, data: Any) -> None:
        async with self._lock:
            conns = list(self._connections.get(room_id, []))
        if not conns:
            return
        dead = []
        for ws in conns:
            try:
                # A stalled client must not hold up progress for everyone else.
                await asyncio.wait_for(ws.send_json(data), timeout=10)
            except Exception as exc:
                logger.debug(f"Dropping websocket in room {room_id}: {exc}")
                dead.append(ws)
        for ws in dead:
            await self.disconnect(room_id, ws)

    async def broadcast(self, data: Any) -> None:
        async with self._lock:
            rooms = list(self._connections)
        for room_id in rooms:
            await self.send(room_id, data)

    def room_count(self, room_id: str) -> int:
        return len(self._connections.get(room_id, []))


ws_manager = ConnectionManager()
