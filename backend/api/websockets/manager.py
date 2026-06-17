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
        # Per-room lock so concurrent send() calls (e.g. a burst of agent tokens
        # scheduled as separate tasks) never overlap a single WebSocket's
        # send_json, which Starlette does not allow.
        self._send_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
                self._send_locks.pop(room_id, None)

    async def send(self, room_id: str, data: Any) -> None:
        async with self._send_locks[room_id]:
            async with self._lock:
                conns = list(self._connections.get(room_id, []))
            dead = []
            for ws in conns:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                await self.disconnect(room_id, ws)

    async def broadcast(self, data: Any) -> None:
        async with self._lock:
            all_conns = [ws for conns in self._connections.values() for ws in conns]
        dead = []
        for ws in all_conns:
            try:
                await ws.send_json(data)
            except Exception:
                logger.debug("Dropping dead websocket during broadcast", exc_info=True)
                dead.append(ws)
        for ws in dead:
            for room_id in list(self._connections.keys()):
                await self.disconnect(room_id, ws)

    def room_count(self, room_id: str) -> int:
        return len(self._connections.get(room_id, []))


ws_manager = ConnectionManager()
