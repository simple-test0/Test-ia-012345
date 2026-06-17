from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.websockets.manager import ws_manager
from core.security import ws_token_ok

ws_router = APIRouter()


@ws_router.websocket("/ws/training/{run_id}")
async def training_websocket(websocket: WebSocket, run_id: str, token: str = ""):
    if not ws_token_ok(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(run_id, websocket)
