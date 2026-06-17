import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from api.websockets.manager import ws_manager
from core.database import AsyncSessionLocal
from models.agent_session import AgentSession
from services.agent.ollama_client import ollama_client
from services.agent.planner import ReactAgent

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws/agent/{session_id}")
async def agent_websocket(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)
    loop = asyncio.get_running_loop()

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

            # 1) Load session state, then release the DB connection before the
            #    (potentially long) LLM stream.
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
                session = result.scalar_one_or_none()
                if session is None:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue
                history = list(session.messages or [])
                tools_used = list(session.tools_used or [])
                system_prompt = session.system_prompt or ""

            history.append({"role": "user", "content": user_content})

            run_messages = list(history)
            if system_prompt:
                run_messages = [{"role": "system", "content": system_prompt}] + run_messages

            # 2) Run the agent outside any DB session. Events are forwarded to the
            #    WS from within this event loop.
            events: list[dict] = []

            def on_event(event: dict):
                events.append(event)
                loop.create_task(ws_manager.send(session_id, event))

            agent = ReactAgent(client=ollama_client, model=model_id)
            try:
                assistant_response = await agent.run(messages=run_messages, on_event=on_event)
            except Exception as exc:
                logger.exception("Agent run failed")
                await ws_manager.send(session_id, {"type": "error", "message": str(exc)})
                continue

            history.append({"role": "assistant", "content": assistant_response})
            for ev in events:
                if ev.get("type") == "tool_call":
                    name = ev.get("tool_name")
                    if name and name not in tools_used:
                        tools_used.append(name)

            # 3) Persist with a fresh, short-lived session.
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
                session = result.scalar_one_or_none()
                if session is not None:
                    session.messages = history
                    session.tools_used = tools_used
                    await db.commit()

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(session_id, websocket)
