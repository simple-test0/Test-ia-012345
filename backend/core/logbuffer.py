import asyncio
import logging
from collections import deque
from typing import Optional

# Routine polling endpoints — their access-log lines repeat every few seconds
# and would drown the Console in noise.
_NOISY_PATHS = (
    "/health",
    "/api/v1/hardware/info",
    "/api/v1/hardware/recommendations",
    "/api/v1/image/pipelines",
    "/api/v1/system/logs",
)


class RingBufferLogHandler(logging.Handler):
    """Keep the last N log records in memory and stream new ones to the
    "logs" WebSocket room, so the frontend Console page can tail the server.
    """

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self._records: deque = deque(maxlen=capacity)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seq = 0

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at startup; without a loop, records are only buffered."""
        self._loop = loop

    def tail(self, limit: int = 500) -> list:
        return list(self._records)[-limit:]

    def emit(self, record: logging.LogRecord) -> None:
        # Never let the console feed on itself (WS send errors would loop).
        if record.name.startswith("api.websockets"):
            return
        try:
            message = self.format(record)
        except Exception:
            return
        # Skip the frontend's routine polling: it repeats every few seconds
        # and buries the interesting lines.
        if record.name == "uvicorn.access" and any(p in message for p in _NOISY_PATHS):
            return
        self._seq += 1
        entry = {
            "type": "log",
            "id": self._seq,
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        self._records.append(entry)

        # emit() runs on whatever thread logged (worker/executor threads
        # included) — hop to the event loop to broadcast.
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._broadcast, entry)
            except RuntimeError:
                pass  # loop shutting down

    @staticmethod
    def _broadcast(entry: dict) -> None:
        from api.websockets.manager import ws_manager

        asyncio.ensure_future(ws_manager.send("logs", entry))


log_buffer = RingBufferLogHandler()
log_buffer.setFormatter(logging.Formatter("%(message)s"))
