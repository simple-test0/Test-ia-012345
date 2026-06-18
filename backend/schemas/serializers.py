"""Centralised serialisers turning ORM rows into plain JSON-ready dicts.

Kept as functions (not Pydantic response models) so the existing API response
shapes are preserved exactly while the dict-building logic lives in one place.
"""

from models.dataset import Dataset
from models.diffusion_model import DiffusionModel
from models.image_job import ImageJob
from models.training_run import TrainingRun


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# ── Diffusion models ──────────────────────────────────────────────────────────

def serialize_diffusion_model(m: DiffusionModel, vram_mb: int) -> dict:
    """Serialise a user-downloaded diffusion model row."""
    if m.status == "ready":
        progress = 100
    elif m.status == "downloading":
        # Lazy import to keep this module free of service-layer dependencies.
        from services.image_gen.hf_connector import download_progress
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


# ── Image jobs ────────────────────────────────────────────────────────────────

def serialize_image_job(job: ImageJob, images: list[str], detail: bool = False) -> dict:
    """Serialise an image job. `images` is the precomputed list of data URLs.

    detail=False trims the prompt (history list view); detail=True returns the
    full record including generation parameters.
    """
    base = {
        "id": job.id,
        "job_id": job.id,
        "status": job.status,
        "model_id": job.model_id,
        "width": job.width,
        "height": job.height,
        "steps": job.steps,
        "seed": job.seed,
        "output_paths": job.output_paths,
        "images": images,
        "duration_ms": job.duration_ms,
        "created_at": _iso(job.created_at),
    }
    if not detail:
        base["prompt"] = (job.prompt or "")[:100]
        return base

    base.update({
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "cfg_scale": job.cfg_scale,
        "sampler": job.sampler,
        "num_images": job.num_images,
        "error_message": job.error_message,
        "completed_at": _iso(job.completed_at),
    })
    return base


# ── Datasets ──────────────────────────────────────────────────────────────────

def serialize_dataset(d: Dataset) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "source": d.source,
        "source_identifier": d.source_identifier,
        "task_type": d.task_type,
        "num_samples": d.num_samples,
        "num_classes": d.num_classes,
        "class_names": d.class_names,
        "local_path": d.local_path,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "error_message": d.error_message,
        "created_at": _iso(d.created_at),
    }


# ── Training runs ─────────────────────────────────────────────────────────────

def serialize_run(r: TrainingRun) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "status": r.status,
        "architecture": r.architecture,
        "arch_config": r.arch_config,
        "training_config": r.training_config,
        "dataset_id": r.dataset_id,
        "hardware_snapshot": r.hardware_snapshot,
        "metrics_history": r.metrics_history,
        "best_checkpoint_path": r.best_checkpoint_path,
        "current_epoch": r.current_epoch,
        "total_epochs": r.total_epochs,
        "error_message": r.error_message,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "completed_at": _iso(r.completed_at),
    }
