import asyncio
import contextlib
import logging
import random
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, get_db
from hardware.detector import get_primary_vram_mb
from models.diffusion_model import DiffusionModel
from models.image_job import ImageJob
from schemas import serialize_diffusion_model, serialize_image_job
from services.image_gen.hf_connector import download_hf_model, search_hf_models
from services.image_gen.model_registry import (
    curated_models,
    get_compatible_models,
    resolve_model,
)
from services.image_gen.pipeline_manager import image_to_data_url

logger = logging.getLogger(__name__)

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
    lora: str | None = None


class HFModelDownloadRequest(BaseModel):
    repo_id: str
    name: str | None = None


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
        models.append(serialize_diffusion_model(m, vram_mb))

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
    seed = req.seed if req.seed != -1 else random.randint(0, 2 ** 31 - 1)

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
    return serialize_diffusion_model(rec, get_primary_vram_mb())


@router.delete("/hf/models/{model_id}")
async def hf_model_delete(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if rec.local_path:
        with contextlib.suppress(Exception):
            shutil.rmtree(Path(rec.local_path), ignore_errors=True)

    await db.delete(rec)
    await db.commit()
    return {"deleted": model_id}


def _job_images(output_paths, thumbnail: bool = False) -> list:
    """Return saved images as ready-to-render `data:` URLs.

    thumbnail=True downsizes to small JPEGs (used for the history list to keep
    payloads light); otherwise full-resolution PNGs are returned. Each file is
    opened exactly once.
    """
    images = []
    for p in output_paths or []:
        try:
            with PILImage.open(p) as img:
                if thumbnail:
                    img.thumbnail((384, 384))
                    images.append(image_to_data_url(img, "JPEG"))
                else:
                    images.append(image_to_data_url(img, "PNG"))
        except FileNotFoundError:
            logger.warning("Image file missing on disk: %s", p)
        except Exception as exc:
            logger.warning("Failed to encode image %s: %s", p, exc)
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
        serialize_image_job(j, _job_images(j.output_paths, thumbnail=True))
        for j in jobs
    ]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_image_job(job, _job_images(job.output_paths), detail=True)
