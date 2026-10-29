import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.agent_session import AgentSession
from services.agent.ollama_client import ollama_client
from services.agent.tool_registry import list_tools

router = APIRouter(prefix="/agent", tags=["agent"])


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow `model_id`

    name: str = Field("New Session", max_length=256)
    model_id: str = "llama3"
    system_prompt: str = "You are a helpful AI assistant."


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow `model_id`

    name: Optional[str] = Field(None, max_length=256)
    model_id: Optional[str] = None
    system_prompt: Optional[str] = None


@router.get("/models")
async def list_ollama_models():
    models = await ollama_client.list_models()
    return {"available": models is not None, "models": models or []}


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


def _summary(s: AgentSession) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "model_id": s.model_id,
        "message_count": len(s.messages or []),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(100)
    )
    return [_summary(s) for s in result.scalars().all()]


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
    await db.refresh(session)
    return _summary(session)


async def _get_or_404(session_id: str, db: AsyncSession) -> AgentSession:
    result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await _get_or_404(session_id, db)
    return {
        "id": session.id,
        "name": session.name,
        "model_id": session.model_id,
        "system_prompt": session.system_prompt,
        "messages": session.messages,
        "tools_used": session.tools_used,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str, req: UpdateSessionRequest, db: AsyncSession = Depends(get_db)
):
    session = await _get_or_404(session_id, db)
    for field in ("name", "model_id", "system_prompt"):
        value = getattr(req, field)
        if value is not None:
            setattr(session, field, value)
    await db.commit()
    await db.refresh(session)
    return _summary(session)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await _get_or_404(session_id, db)
    await db.delete(session)
    await db.commit()
    return {"deleted": session_id}
