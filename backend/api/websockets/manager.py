import asyncio
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import WebSocket


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
        for ws in all_conns:
            try:
                await ws.send_json(data)
            except Exception:
                pass

    def room_count(self, room_id: str) -> int:
        return len(self._connections.get(room_id, []))


ws_manager = ConnectionManager()
