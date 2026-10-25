from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.websockets.manager import ws_manager
from core import security
from core.logbuffer import log_buffer

ws_router = APIRouter()


@ws_router.websocket("/ws/logs")
async def logs_websocket(websocket: WebSocket, token: str = ""):
    if not security.ws_token_ok(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_manager.connect("logs", websocket)
    try:
        # Backlog first, then live records arrive via the "logs" room.
        for entry in log_buffer.tail(300):
            await websocket.send_json(entry)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect("logs", websocket)
