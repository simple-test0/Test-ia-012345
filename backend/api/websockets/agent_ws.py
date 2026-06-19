import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from api.websockets.manager import ws_manager
from core.database import AsyncSessionLocal
from core.security import ws_token_ok
from models.agent_session import AgentSession
from services.agent.ollama_client import OllamaClient
from services.agent.planner import ReactAgent

ws_router = APIRouter()


@ws_router.websocket("/ws/agent/{session_id}")
async def agent_websocket(websocket: WebSocket, session_id: str, token: str = ""):
    if not ws_token_ok(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_manager.connect(session_id, websocket)
    client = OllamaClient()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            user_content = msg.get("content", "").strip()
            if not user_content:
                continue

            await _handle_message(
                websocket,
                session_id,
                client,
                user_content,
                model_id=msg.get("model_id", "llama3"),
            )
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(session_id, websocket)


async def _handle_message(
    websocket: WebSocket,
    session_id: str,
    client: OllamaClient,
    user_content: str,
    model_id: str,
) -> None:
    """Run one agent turn for a received user message and persist the result.

    Defined outside the receive loop so the streaming `on_event` callback does
    not close over loop variables.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            await websocket.send_json({"type": "error", "message": "Session not found"})
            return

        messages = list(session.messages or [])
        messages.append({"role": "user", "content": user_content})

        agent = ReactAgent(client=client, model=model_id)
        events: list[dict] = []
        loop = asyncio.get_running_loop()

        def on_event(event: dict):
            events.append(event)
            loop.create_task(ws_manager.send(session_id, event))

        try:
            assistant_response = await agent.run(messages=messages, on_event=on_event)
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            return

        messages.append({"role": "assistant", "content": assistant_response})
        tools_used = list(session.tools_used or [])
        for ev in events:
            if ev.get("type") == "tool_call":
                tool_name = ev.get("tool_name")
                if tool_name and tool_name not in tools_used:
                    tools_used.append(tool_name)

        session.messages = messages
        session.tools_used = tools_used
        await db.commit()
