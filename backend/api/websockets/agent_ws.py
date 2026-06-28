import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from api.websockets.manager import ws_manager
from core.database import AsyncSessionLocal
from core.security import ws_token_ok
from models.agent_session import AgentSession
from services.agent.ollama_client import ollama_client
from services.agent.planner import ReactAgent

logger = logging.getLogger(__name__)

ws_router = APIRouter()


async def _run_turn(session_id: str, user_content: str, model_id: str) -> None:
    """Run one agent turn: load history, stream the reply, persist the result.

    The DB connection is held only to read the session and (separately) to write
    it back — never across the LLM stream. Streamed events are pushed onto a
    queue and forwarded by a single drainer task, so sends are ordered and never
    overlap on the same socket.
    """
    # 1) Load session state, then release the DB connection.
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            await ws_manager.send(session_id, {"type": "error", "message": "Session not found"})
            return
        history = list(session.messages or [])
        tools_used = list(session.tools_used or [])
        system_prompt = session.system_prompt or ""

    history.append({"role": "user", "content": user_content})
    run_messages = (
        [{"role": "system", "content": system_prompt}, *history] if system_prompt else list(history)
    )

    # 2) Stream the agent outside any DB session.
    events: list[dict] = []
    send_queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict) -> None:
        events.append(event)
        send_queue.put_nowait(event)

    async def _drain() -> None:
        while True:
            event = await send_queue.get()
            if event is None:
                break
            await ws_manager.send(session_id, event)

    drain_task = asyncio.create_task(_drain())
    agent = ReactAgent(client=ollama_client, model=model_id)
    try:
        assistant_response = await agent.run(messages=run_messages, on_event=on_event)
    except Exception as exc:
        logger.exception("Agent run failed")
        send_queue.put_nowait({"type": "error", "message": str(exc)})
        return
    finally:
        send_queue.put_nowait(None)
        await drain_task

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


@ws_router.websocket("/ws/agent/{session_id}")
async def agent_websocket(websocket: WebSocket, session_id: str, token: str = ""):
    if not ws_token_ok(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_manager.connect(session_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            user_content = msg.get("content", "").strip()
            model_id = msg.get("model_id", "llama3")
            if user_content:
                await _run_turn(session_id, user_content, model_id)
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(session_id, websocket)
