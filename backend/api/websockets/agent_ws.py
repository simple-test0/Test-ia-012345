import asyncio
import json
import logging
from typing import Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from api.websockets.manager import ws_manager
from core.database import AsyncSessionLocal
from core.security import ws_token_ok
from models.agent_session import AgentSession
from services.agent.ollama_client import OllamaClient
from services.agent.planner import ReactAgent

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# Keep the prompt sent to the model bounded: very long chats slow every reply
# and can overflow small context windows. The full history stays in the DB.
_MAX_HISTORY_MESSAGES = 40

# One turn at a time per session. Turns survive a dropped socket (the answer
# is saved and reloaded on reconnect) and can be stopped with {"type": "stop"}.
_running: Dict[str, asyncio.Task] = {}


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
            if not isinstance(msg, dict) or msg.get("type") == "ping":
                continue

            current = _running.get(session_id)
            busy = current is not None and not current.done()

            if msg.get("type") == "stop":
                if busy:
                    current.cancel()
                continue

            user_content = str(msg.get("content", "")).strip()
            if not user_content:
                continue
            if busy:
                await websocket.send_json({
                    "type": "error",
                    "message": "A reply is already being written — wait or press Stop.",
                })
                continue

            # Run the turn in the background so this loop keeps reading
            # (that is what makes "stop" possible).
            task = asyncio.create_task(
                _run_turn(session_id, user_content, msg.get("model_id"), client)
            )
            _running[session_id] = task
            task.add_done_callback(
                lambda t, sid=session_id: _running.pop(sid, None) if _running.get(sid) is t else None
            )

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(session_id, websocket)


async def _run_turn(session_id: str, user_content: str, model_id, client) -> None:
    try:
        await _handle_message(session_id, user_content, model_id, client)
    except asyncio.CancelledError:
        pass  # stopped by the user; partial answer already saved
    except Exception as exc:
        # Never let one bad turn kill the socket: report and keep going.
        logger.exception("Agent turn failed")
        await ws_manager.send(session_id, {"type": "error", "message": str(exc)})


async def _handle_message(session_id: str, user_content: str, model_id, client) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            await ws_manager.send(session_id, {"type": "error", "message": "Session not found"})
            return

        model = (model_id or session.model_id or "").strip()
        if not model:
            await ws_manager.send(session_id, {
                "type": "error",
                "message": "No model selected — install one with `ollama pull llama3.2`.",
            })
            return

        messages = list(session.messages or [])
        messages.append({"role": "user", "content": user_content})

        agent = ReactAgent(client=client, model=model, system_prompt=session.system_prompt)

        tools_used = list(session.tools_used or [])
        partial: list = []

        async def on_event(event: dict) -> None:
            if event.get("type") == "token":
                partial.append(event.get("content", ""))
            elif event.get("type") == "tool_call":
                name = event.get("tool_name")
                if name and name not in tools_used:
                    tools_used.append(name)
            await ws_manager.send(session_id, event)

        try:
            assistant_response = await agent.run(
                messages=messages[-_MAX_HISTORY_MESSAGES:], on_event=on_event
            )
        except asyncio.CancelledError:
            # Stopped: keep what was written so far (closing the HTTP stream
            # also tells Ollama to stop generating).
            assistant_response = ("".join(partial).rstrip() + "\n\n*[interrompu]*").lstrip()
            await ws_manager.send(session_id, {
                "type": "message_complete", "full_content": assistant_response, "stopped": True,
            })
            _save(session, messages, assistant_response, tools_used, model, user_content)
            await db.commit()
            raise

        _save(session, messages, assistant_response, tools_used, model, user_content)
        await db.commit()


def _save(session, messages, answer, tools_used, model, user_content) -> None:
    messages.append({"role": "assistant", "content": answer})
    session.messages = messages
    session.tools_used = tools_used
    if model != session.model_id:
        session.model_id = model
    # First exchange: name the session after the question (easier to find).
    if len(messages) == 2 and (session.name or "").startswith("Session "):
        session.name = user_content[:60]
