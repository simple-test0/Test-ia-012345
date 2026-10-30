import asyncio
import random
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal, get_db
from core.security import require_api_token_or_query
from core.tasks import spawn
from hardware.detector import get_primary_vram_mb
from models.diffusion_model import DiffusionModel
from models.image_job import ImageJob
from services.image_gen.hf_connector import download_hf_model, download_progress, search_hf_models
from services.image_gen.images import (
    delete_job_files,
    image_urls,
    init_image_path,
    init_image_url,
    is_valid_image_name,
    make_thumbnail,
    save_init_image,
    thumb_path_for,
)
from services.image_gen.model_registry import (
    curated_models,
    get_compatible_models,
    resolve_model,
)
from services.image_gen.pipeline_manager import SAMPLERS

router = APIRouter(prefix="/image", tags=["image-generation"])

# Served without the header-only auth so <img src> and download links work;
# protected by header *or* ?token= instead.
files_router = APIRouter(
    prefix="/image", tags=["image-generation"],
    dependencies=[Depends(require_api_token_or_query)],
)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow `model_id`

    model_id: str = "sd15"
    prompt: str = Field(..., min_length=1, max_length=4000)
    negative_prompt: str = Field("", max_length=4000)
    width: int = Field(512, ge=64, le=2048)
    height: int = Field(512, ge=64, le=2048)
    steps: int = Field(20, ge=1, le=150)
    cfg_scale: float = Field(7.5, ge=0.0, le=30.0)
    seed: int = Field(-1, ge=-1, le=2**32 - 1)
    sampler: str = "DPM++ 2M"
    num_images: int = Field(1, ge=1, le=4)
    # Optional LoRA adapter (HF repo id), applied on top of the base model.
    lora: Optional[str] = Field(None, max_length=512)
    # img2img: source image as a data URL (≈ 20 MB max) and how much to change it
    # (0 = keep the source, 1 = ignore it).
    init_image: Optional[str] = Field(None, max_length=28_000_000)
    strength: float = Field(0.6, ge=0.05, le=1.0)

    @field_validator("width", "height")
    @classmethod
    def _multiple_of_8(cls, v: int) -> int:
        # Diffusion models need dimensions divisible by 8.
        return max(64, v - v % 8)

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt must not be empty")
        return v.strip()

    @field_validator("sampler")
    @classmethod
    def _known_sampler(cls, v: str) -> str:
        return v if v in SAMPLERS else "DPM++ 2M"

    @field_validator("lora")
    @classmethod
    def _clean_lora(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None


class HFModelDownloadRequest(BaseModel):
    repo_id: str = Field(..., max_length=512)
    name: Optional[str] = Field(None, max_length=256)


def _downloaded_model_dict(m: DiffusionModel, vram_mb: int, progress: int = 0) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "description": "",
        "min_vram_mb": m.min_vram_mb or 0,
        "recommended_steps": m.recommended_steps or 25,
        "default_cfg": m.default_cfg if m.default_cfg is not None else 7.5,
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
        "progress": 100 if m.status == "ready" else progress,
        "error_message": m.error_message,
    }


async def _progress_of(m: DiffusionModel) -> int:
    if m.status != "downloading":
        return 0
    # Walks the download folder: run it off the event loop.
    return await asyncio.to_thread(download_progress, m.repo_id, m.total_bytes or 0)


@router.get("/samplers")
async def list_samplers():
    return SAMPLERS


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    vram_mb = await asyncio.to_thread(get_primary_vram_mb)
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
        models.append(_downloaded_model_dict(m, vram_mb, await _progress_of(m)))

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
                detail=f"Model '{rec.name}' is not ready (status: {rec.status})",
            )
        raise HTTPException(status_code=404, detail=f"Model '{req.model_id}' not found")

    worker = request.app.state.generation_worker
    if request.app.state.generation_queue.full():
        raise HTTPException(
            status_code=503,
            detail="The generation queue is full — wait for some jobs to finish.",
        )

    job_id = str(uuid.uuid4())
    seed = req.seed if req.seed != -1 else random.randint(0, 2 ** 32 - 1)

    init_path = None
    width, height = req.width, req.height
    if req.init_image:
        try:
            # The source keeps its aspect ratio, fitted in the requested size.
            init_path, width, height = await asyncio.to_thread(
                save_init_image, job_id, req.init_image, req.width, req.height
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    db_job = ImageJob(
        id=job_id,
        status="queued",
        model_id=req.model_id,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=width,
        height=height,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        seed=seed,
        sampler=req.sampler,
        num_images=req.num_images,
        init_image_path=init_path,
        strength=req.strength if init_path else None,
    )
    db.add(db_job)
    await db.commit()

    queue_job = {
        "id": job_id,
        "model_id": req.model_id,
        "repo_id": resolved.repo_id,
        "prompt": req.prompt,
        # Models like SDXL-Turbo/FLUX ignore (or reject) a negative prompt.
        "negative_prompt": req.negative_prompt if resolved.supports_negative_prompt else "",
        "width": width,
        "height": height,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "seed": seed,
        "num_images": req.num_images,
        "sampler": req.sampler,
        "lora": req.lora,
        "init_image_path": init_path,
        "strength": req.strength,
    }
    try:
        position = worker.enqueue(queue_job)
    except asyncio.QueueFull:
        if init_path:
            await asyncio.to_thread(delete_job_files, [], init_path)
        db_job.status = "failed"
        db_job.error_message = "Queue full"
        await db.commit()
        raise HTTPException(status_code=503, detail="The generation queue is full.")

    return {
        "job_id": job_id,
        "status": "queued",
        "seed": seed,
        "width": width,
        "height": height,
        "init_image": init_image_url(job_id, init_path),
        "queue_size": request.app.state.generation_queue.qsize(),
        "queue_position": position,
    }


# ── Hugging Face connector ──────────────────────────────────────────────────────

@router.get("/hf/search")
async def hf_search(query: str, limit: int = Query(25, ge=1, le=100)):
    query = (query or "").strip()
    if not query:
        return {"results": []}
    try:
        results = await asyncio.to_thread(search_hf_models, query, limit)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Hugging Face search failed: {exc}"
        ) from exc
    return {"results": results}


@router.post("/hf/download")
async def hf_download(req: HFModelDownloadRequest, db: AsyncSession = Depends(get_db)):
    repo_id = req.repo_id.strip().strip("/")
    if not repo_id or repo_id.count("/") != 1 or ".." in repo_id:
        raise HTTPException(status_code=400, detail="repo_id must look like 'owner/name'")

    existing = await db.execute(
        select(DiffusionModel).where(DiffusionModel.repo_id == repo_id)
    )
    rec = existing.scalar_one_or_none()
    # Idempotent: don't re-download a model that's already present/in progress.
    if rec is not None and rec.status in ("ready", "downloading"):
        return {"id": rec.id, "status": rec.status}

    if rec is not None:
        # Retry after an error: reuse the record (repo_id is unique).
        rec.status = "downloading"
        rec.error_message = None
        db_id = rec.id
    else:
        db_id = str(uuid.uuid4())
        db.add(DiffusionModel(
            id=db_id,
            name=req.name or repo_id.split("/")[-1],
            repo_id=repo_id,
            status="downloading",
        ))
    await db.commit()

    spawn(download_hf_model(db_id, repo_id, AsyncSessionLocal), name=f"hf-download-{repo_id}")
    return {"id": db_id, "status": "downloading"}


@router.get("/hf/models/{model_id}")
async def hf_model_status(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Model not found")
    vram_mb = await asyncio.to_thread(get_primary_vram_mb)
    return _downloaded_model_dict(rec, vram_mb, await _progress_of(rec))


@router.delete("/hf/models/{model_id}")
async def hf_model_delete(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # Remove the whole HF cache folder of the repo (snapshots + blobs), not just
    # the snapshot symlinks, so the disk space is actually freed.
    from services.image_gen.hf_connector import _repo_cache_path

    folder = _repo_cache_path(rec.repo_id)
    await asyncio.to_thread(shutil.rmtree, folder, True)

    await db.delete(rec)
    await db.commit()
    return {"deleted": model_id}


# ── Jobs ──────────────────────────────────────────────────────────────────────

def _job_summary(j: ImageJob) -> dict:
    return {
        "id": j.id,
        "job_id": j.id,
        "status": j.status,
        "model_id": j.model_id,
        "prompt": j.prompt,
        "negative_prompt": j.negative_prompt,
        "width": j.width,
        "height": j.height,
        "steps": j.steps,
        "cfg_scale": j.cfg_scale,
        "seed": j.seed,
        "sampler": j.sampler,
        "num_images": j.num_images,
        "init_image": init_image_url(j.id, j.init_image_path),
        "strength": j.strength,
        "images": image_urls(j.output_paths, thumbnail=True),
        "full_images": image_urls(j.output_paths, thumbnail=False),
        "error_message": j.error_message,
        "duration_ms": j.duration_ms,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    # Images are referenced by URL (cached by the browser) — no encoding here.
    result = await db.execute(
        select(ImageJob).order_by(ImageJob.created_at.desc()).limit(limit).offset(offset)
    )
    return [_job_summary(j) for j in result.scalars().all()]


@router.get("/jobs/count")
async def count_jobs(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(ImageJob))
    return {"total": total or 0}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    data = _job_summary(job)
    worker = getattr(request.app.state, "generation_worker", None)
    if worker and job.status == "queued":
        data["queue_position"] = worker.position(job_id)
    return data


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from api.websockets.manager import ws_manager

    worker = request.app.state.generation_worker
    state = worker.cancel(job_id)
    if state is None:
        raise HTTPException(status_code=409, detail="Job is not queued or running")
    if state == "queued":
        result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = "cancelled"
            await db.commit()
        await ws_manager.send(job_id, {"type": "cancelled", "job_id": job_id})
        await worker.broadcast_positions()
    return {"cancelled": job_id, "was": state}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("queued", "running"):
        request.app.state.generation_worker.cancel(job_id)
    await asyncio.to_thread(delete_job_files, job.output_paths, job.init_image_path)
    await db.delete(job)
    await db.commit()
    return {"deleted": job_id}


@files_router.get("/files/init/{name}")
async def get_init_image(name: str):
    job_id = name.removesuffix(".png")
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found")
    path = init_image_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(
        path, media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@files_router.get("/files/{name}")
async def get_image_file(name: str, thumb: bool = False):
    if not is_valid_image_name(name):
        raise HTTPException(status_code=404, detail="Image not found")
    path = settings.images_dir / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = "image/png"
    if thumb:
        # Older jobs may predate thumbnails: create them on demand.
        tp = thumb_path_for(path)
        if not tp.exists():
            tp = await asyncio.to_thread(make_thumbnail, path)
        if tp is not None and Path(tp).exists():
            path, media_type = Path(tp), "image/jpeg"
    # File names are unique per job and never rewritten: cache aggressively.
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
