import random
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.image_job import ImageJob
from services.image_gen.model_registry import MODEL_REGISTRY, get_model, get_compatible_models
from hardware.detector import get_primary_vram_mb

router = APIRouter(prefix="/image", tags=["image-generation"])


class GenerateRequest(BaseModel):
    model_id: str = "sd15"
    prompt: str
    negative_prompt: str = ""
    width: int = Field(512, ge=64, le=2048)
    height: int = Field(512, ge=64, le=2048)
    steps: int = Field(20, ge=1, le=150)
    cfg_scale: float = Field(7.5, ge=0.0, le=30.0)
    seed: int = Field(-1)
    sampler: str = "DPM++ 2M"
    num_images: int = Field(1, ge=1, le=4)


@router.get("/models")
async def list_models():
    vram_mb = get_primary_vram_mb()
    compatible = {m.id for m in get_compatible_models(vram_mb)}
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "min_vram_mb": m.min_vram_mb,
            "recommended_steps": m.recommended_steps,
            "default_cfg": m.default_cfg,
            "default_width": m.default_width,
            "default_height": m.default_height,
            "tags": m.tags,
            "compatible": m.id in compatible,
        }
        for m in MODEL_REGISTRY
    ]


@router.post("/generate")
async def generate(req: GenerateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    model_info = get_model(req.model_id)
    if model_info is None:
        raise HTTPException(status_code=404, detail=f"Model '{req.model_id}' not found")

    job_id = str(uuid.uuid4())
    seed = req.seed if req.seed != -1 else random.randint(0, 2 ** 32 - 1)

    db_job = ImageJob(
        id=job_id,
        status="queued",
        model_id=req.model_id,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=req.width,
        height=req.height,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        seed=seed,
        sampler=req.sampler,
        num_images=req.num_images,
    )
    db.add(db_job)
    await db.commit()

    generation_queue = request.app.state.generation_queue
    queue_job = {
        "id": job_id,
        "model_id": req.model_id,
        "repo_id": model_info.repo_id,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "seed": seed,
        "num_images": req.num_images,
    }
    await generation_queue.put(queue_job)

    return {"job_id": job_id, "status": "queued", "queue_size": generation_queue.qsize()}


@router.get("/jobs")
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ImageJob).order_by(ImageJob.created_at.desc()).limit(limit).offset(offset)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "status": j.status,
            "model_id": j.model_id,
            "prompt": j.prompt[:100],
            "width": j.width,
            "height": j.height,
            "steps": j.steps,
            "seed": j.seed,
            "output_paths": j.output_paths,
            "duration_ms": j.duration_ms,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "model_id": job.model_id,
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "width": job.width,
        "height": job.height,
        "steps": job.steps,
        "cfg_scale": job.cfg_scale,
        "seed": job.seed,
        "sampler": job.sampler,
        "num_images": job.num_images,
        "output_paths": job.output_paths,
        "error_message": job.error_message,
        "duration_ms": job.duration_ms,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
