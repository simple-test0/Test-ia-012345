from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.websockets.manager import ws_manager

ws_router = APIRouter()


@ws_router.websocket("/ws/training/{run_id}")
async def training_websocket(websocket: WebSocket, run_id: str):
    await ws_manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(run_id, websocket)
