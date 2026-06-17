import asyncio
import random
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, get_db
from models.diffusion_model import DiffusionModel
from models.image_job import ImageJob
from services.image_gen.hf_connector import download_hf_model, download_progress, search_hf_models
from services.image_gen.model_registry import (
    curated_models,
    get_compatible_models,
    resolve_model,
)
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
    # Optional LoRA adapter (HF repo id), applied on top of the base model.
    lora: Optional[str] = None


class HFModelDownloadRequest(BaseModel):
    repo_id: str
    name: Optional[str] = None


def _downloaded_model_dict(m: DiffusionModel, vram_mb: int) -> dict:
    if m.status == "ready":
        progress = 100
    elif m.status == "downloading":
        progress = download_progress(m.repo_id, m.total_bytes or 0)
    else:
        progress = 0
    return {
        "id": m.id,
        "name": m.name,
        "description": "",
        "min_vram_mb": m.min_vram_mb or 0,
        "recommended_steps": m.recommended_steps or 25,
        "default_cfg": m.default_cfg or 7.5,
        "default_width": m.default_width or 512,
        "default_height": m.default_height or 512,
        "tags": m.tags or [],
        "compatible": (m.min_vram_mb or 0) <= vram_mb,
        "source": "downloaded",
        "recommended": False,
        "status": m.status,
        "repo_id": m.repo_id,
        "gated": m.gated,
        "size_bytes": m.size_bytes,
        "total_bytes": m.total_bytes,
        "progress": progress,
        "error_message": m.error_message,
    }


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    vram_mb = get_primary_vram_mb()
    compatible = {m.id for m in get_compatible_models(vram_mb)}

    # Curated (recommended) models first.
    models = [
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
            "source": "curated",
            "recommended": True,
            "status": "ready",
            "repo_id": m.repo_id,
            "gated": m.gated,
        }
        for m in curated_models()
    ]

    # Then user-downloaded models.
    result = await db.execute(
        select(DiffusionModel).order_by(DiffusionModel.created_at.desc())
    )
    for m in result.scalars().all():
        models.append(_downloaded_model_dict(m, vram_mb))

    return models


@router.post("/generate")
async def generate(req: GenerateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    resolved = await resolve_model(req.model_id, db)
    if resolved is None:
        # Distinguish "downloading/error" from "missing" for a clearer message.
        existing = await db.execute(
            select(DiffusionModel).where(DiffusionModel.id == req.model_id)
        )
        rec = existing.scalar_one_or_none()
        if rec is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Model '{req.model_id}' is not ready (status: {rec.status})",
            )
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
        "repo_id": resolved.repo_id,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "seed": seed,
        "num_images": req.num_images,
        "sampler": req.sampler,
        "lora": req.lora,
    }
    await generation_queue.put(queue_job)

    queue_size = generation_queue.qsize()
    return {
        "job_id": job_id,
        "status": "queued",
        "queue_size": queue_size,
        "queue_position": queue_size,
    }


# ── Hugging Face connector ──────────────────────────────────────────────────────

@router.get("/hf/search")
async def hf_search(query: str, limit: int = 25):
    query = (query or "").strip()
    if not query:
        return {"results": []}
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: search_hf_models(query, limit)
    )
    return {"results": results}


@router.post("/hf/download")
async def hf_download(req: HFModelDownloadRequest, db: AsyncSession = Depends(get_db)):
    repo_id = req.repo_id.strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")

    # Idempotent: don't re-download a model that's already present/in progress.
    existing = await db.execute(
        select(DiffusionModel).where(DiffusionModel.repo_id == repo_id)
    )
    rec = existing.scalar_one_or_none()
    if rec is not None and rec.status in ("ready", "downloading"):
        return {"id": rec.id, "status": rec.status}

    db_id = str(uuid.uuid4())
    model = DiffusionModel(
        id=db_id,
        name=req.name or repo_id.split("/")[-1],
        repo_id=repo_id,
        status="downloading",
    )
    db.add(model)
    await db.commit()

    asyncio.create_task(download_hf_model(db_id, repo_id, AsyncSessionLocal))
    return {"id": db_id, "status": "downloading"}


@router.get("/hf/models/{model_id}")
async def hf_model_status(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return _downloaded_model_dict(rec, get_primary_vram_mb())


@router.delete("/hf/models/{model_id}")
async def hf_model_delete(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if rec.local_path:
        try:
            shutil.rmtree(Path(rec.local_path), ignore_errors=True)
        except Exception:
            pass

    await db.delete(rec)
    await db.commit()
    return {"deleted": model_id}


def _job_images(output_paths, thumbnail: bool = False) -> list:
    """Return saved images as ready-to-render `data:` URLs.

    thumbnail=True downsizes to small JPEGs (used for the history list to keep
    payloads light); otherwise full-resolution PNGs are returned.
    """
    from PIL import Image as PILImage

    from services.image_gen.pipeline_manager import image_to_data_url

    images = []
    for p in output_paths or []:
        try:
            if thumbnail:
                img = PILImage.open(p)
                img.thumbnail((384, 384))
                images.append(image_to_data_url(img, "JPEG"))
            else:
                img = PILImage.open(p)
                images.append(image_to_data_url(img, "PNG"))
        except Exception:
            pass
    return images


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
            "job_id": j.id,
            "status": j.status,
            "model_id": j.model_id,
            "prompt": j.prompt[:100],
            "width": j.width,
            "height": j.height,
            "steps": j.steps,
            "seed": j.seed,
            "output_paths": j.output_paths,
            "images": _job_images(j.output_paths, thumbnail=True),
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
        "job_id": job.id,
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
        "images": _job_images(job.output_paths),
        "error_message": job.error_message,
        "duration_ms": job.duration_ms,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
