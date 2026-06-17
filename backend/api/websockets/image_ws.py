from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.websockets.manager import ws_manager
from core.security import ws_token_ok

ws_router = APIRouter()


@ws_router.websocket("/ws/image/{job_id}")
async def image_websocket(websocket: WebSocket, job_id: str, token: str = ""):
    if not ws_token_ok(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(job_id, websocket)
