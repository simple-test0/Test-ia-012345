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
            model_id = msg.get("model_id", "llama3")

            if not user_content:
                continue

            # Load session history
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
                session = result.scalar_one_or_none()
                if session is None:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue

                messages = list(session.messages or [])
                messages.append({"role": "user", "content": user_content})

                agent = ReactAgent(client=client, model=model_id)

                events = []

                def on_event(event: dict):
                    # Called from within the event loop (between awaits in
                    # agent.run), so we can schedule the send directly.
                    events.append(event)
                    asyncio.ensure_future(ws_manager.send(session_id, event))

                assistant_response = await agent.run(messages=messages, on_event=on_event)

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

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(session_id, websocket)
