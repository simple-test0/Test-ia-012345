import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.agent_session import AgentSession
from services.agent.ollama_client import ollama_client
from services.agent.tool_registry import list_tools

router = APIRouter(prefix="/agent", tags=["agent"])


class CreateSessionRequest(BaseModel):
    name: str = "New Session"
    model_id: str = "llama3"
    system_prompt: str = "You are a helpful AI assistant."


@router.get("/models")
async def list_ollama_models():
    available = await ollama_client.list_models()
    reachable = await ollama_client.is_available()
    return {"available": reachable, "models": available}


@router.get("/tools")
async def get_tools():
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in list_tools()
    ]


@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(50)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "model_id": s.model_id,
            "message_count": len(s.messages or []),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@router.post("/sessions")
async def create_session(req: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    session = AgentSession(
        id=str(uuid.uuid4()),
        name=req.name,
        model_id=req.model_id,
        system_prompt=req.system_prompt,
        messages=[],
        tools_used=[],
    )
    db.add(session)
    await db.commit()
    return {"id": session.id, "name": session.name}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "name": session.name,
        "model_id": session.model_id,
        "system_prompt": session.system_prompt,
        "messages": session.messages,
        "tools_used": session.tools_used,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"deleted": session_id}
