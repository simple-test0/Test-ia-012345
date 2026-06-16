from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.websockets.manager import ws_manager

ws_router = APIRouter()


@ws_router.websocket("/ws/image/{job_id}")
async def image_websocket(websocket: WebSocket, job_id: str):
    await ws_manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(job_id, websocket)
