import asyncio
import logging
import queue as queue_mod
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.websockets.manager import ws_manager
from core.config import settings, utcnow
from core.database import AsyncSessionLocal, get_db
from core.tasks import spawn
from hardware.detector import detect_hardware_cached, effective_vram_mb
from models.dataset import Dataset
from models.training_run import TrainingRun
from services.labs.architecture_registry import get_arch, list_archs
from services.labs.exporter import export_model
from services.labs.trainer import training_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/labs", tags=["labs"])

_TASK_TYPES = ("classification", "detection", "segmentation", "generation", "nlp")


# ── Architectures ─────────────────────────────────────────────────────────────

@router.get("/architectures")
async def get_architectures(vram_mb: int = 0, task_type: str = ""):
    archs = list_archs(vram_mb=vram_mb, task_type=task_type)
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "task_types": a.task_types,
            "min_vram_mb": a.min_vram_mb,
            "default_config": a.default_config,
            "param_schema": a.param_schema,
            "tags": a.tags,
        }
        for a in archs
    ]


# ── Datasets ──────────────────────────────────────────────────────────────────

@router.get("/datasets")
async def list_datasets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dataset).order_by(Dataset.created_at.desc()))
    datasets = result.scalars().all()
    return [_dataset_dict(d) for d in datasets]


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    return _dataset_dict(await _get_dataset_or_404(dataset_id, db))


class HFDatasetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    hf_id: str = Field(..., min_length=1, max_length=512)
    task_type: str = "classification"


@router.post("/datasets/huggingface")
async def download_hf_dataset(req: HFDatasetRequest, db: AsyncSession = Depends(get_db)):
    from services.labs.dataset_manager import download_huggingface_dataset

    task_type = req.task_type if req.task_type in _TASK_TYPES else "classification"
    ds_id = str(uuid.uuid4())
    record = Dataset(
        id=ds_id,
        name=req.name.strip(),
        source="huggingface",
        source_identifier=req.hf_id.strip(),
        task_type=task_type,
        status="downloading",
    )
    db.add(record)
    await db.commit()

    spawn(
        download_huggingface_dataset(ds_id, req.hf_id.strip(), task_type, AsyncSessionLocal),
        name=f"dataset-{ds_id}",
    )
    return {"id": ds_id, "status": "downloading"}


@router.post("/datasets/upload")
async def upload_dataset(
    name: str = Form(..., min_length=1, max_length=256),
    task_type: str = Form("classification"),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    from services.labs.dataset_manager import save_uploads

    if task_type not in _TASK_TYPES:
        task_type = "classification"
    ds_id = str(uuid.uuid4())
    dataset_dir = settings.datasets_dir / ds_id
    try:
        num_files, total_bytes = await save_uploads(dataset_dir, files)
    except ValueError as exc:
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise

    record = Dataset(
        id=ds_id,
        name=name.strip(),
        source="upload",
        task_type=task_type,
        status="ready",
        local_path=str(dataset_dir),
        num_samples=num_files,
        size_bytes=total_bytes,
    )
    db.add(record)
    await db.commit()
    return _dataset_dict(record)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    ds = await _get_dataset_or_404(dataset_id, db)
    # Only ever delete inside our own datasets folder.
    folder = settings.datasets_dir / ds.id
    await asyncio.to_thread(shutil.rmtree, folder, True)
    await db.delete(ds)
    await db.commit()
    return {"deleted": dataset_id}


async def _get_dataset_or_404(dataset_id: str, db: AsyncSession) -> Dataset:
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds


# ── Training Runs ─────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    architecture: str
    arch_config: Dict[str, Any] = Field(default_factory=dict)
    training_config: Dict[str, Any] = Field(default_factory=dict)
    dataset_id: Optional[str] = None


@router.get("/runs")
async def list_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrainingRun).order_by(TrainingRun.created_at.desc()))
    runs = result.scalars().all()
    return [_run_dict(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    return _run_dict(await _get_run_or_404(run_id, db))


async def _get_run_or_404(run_id: str, db: AsyncSession) -> TrainingRun:
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs")
async def create_run(req: CreateRunRequest, db: AsyncSession = Depends(get_db)):
    spec = get_arch(req.architecture)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Architecture '{req.architecture}' not found")

    # Start from the architecture defaults so a partial config still works.
    arch_config = {**spec.default_config, **(req.arch_config or {})}
    training_config = dict(req.training_config or {})
    try:
        epochs = int(training_config.get("epochs", 10))
        batch_size = int(training_config.get("batch_size", 16))
        lr = float(training_config.get("learning_rate", 3e-4))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid training config: {exc}") from exc
    if not (1 <= epochs <= 10000 and 1 <= batch_size <= 65536 and 0 < lr < 10):
        raise HTTPException(
            status_code=422,
            detail="epochs must be 1-10000, batch_size 1-65536 and learning_rate in (0, 10)",
        )

    dataset_path = None
    if req.dataset_id:
        result = await db.execute(select(Dataset).where(Dataset.id == req.dataset_id))
        ds = result.scalar_one_or_none()
        if ds is None or ds.status != "ready":
            raise HTTPException(status_code=409, detail="Dataset not found or not ready")
        dataset_path = ds.local_path

    hw = await asyncio.to_thread(detect_hardware_cached)
    run_id = str(uuid.uuid4())
    checkpoint_dir = str(settings.models_dir / "trained" / run_id / "checkpoints")

    run = TrainingRun(
        id=run_id,
        name=req.name.strip(),
        status="running",
        architecture=req.architecture,
        arch_config=arch_config,
        training_config=training_config,
        dataset_id=req.dataset_id,
        total_epochs=epochs,
        started_at=utcnow(),
        hardware_snapshot={
            "vram_mb": effective_vram_mb(hw),
            "ram_mb": hw.ram_total_mb,
            "cpu_cores": hw.cpu.logical_cores if hw.cpu else 0,
            "accelerator": hw.accelerator,
        },
    )
    db.add(run)
    await db.commit()

    # Start training subprocess (spawning takes a moment: off the event loop).
    q = await asyncio.to_thread(
        training_manager.start,
        run_id=run_id,
        arch_id=req.architecture,
        arch_config=arch_config,
        training_config=training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )
    spawn(_drain_queue(run_id, q), name=f"training-{run_id}")
    return {"id": run_id, "status": "running"}


async def _update_run(run_id: str, **fields) -> None:
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(TrainingRun).where(TrainingRun.id == run_id))
        rec = r.scalar_one_or_none()
        if rec is None:
            return
        history_event = fields.pop("_append_metric", None)
        if history_event is not None:
            rec.metrics_history = list(rec.metrics_history or []) + [history_event]
        for k, v in fields.items():
            setattr(rec, k, v)
        await session.commit()


async def _drain_queue(run_id: str, q) -> None:
    """Forward subprocess events to the WebSocket and persist progress."""

    def _get():
        return q.get(timeout=1.0)

    while True:
        try:
            event = await asyncio.to_thread(_get)
        except queue_mod.Empty:
            if training_manager.is_alive(run_id):
                continue
            # Process gone: read what it flushed last, then report a crash
            # (OOM kill, segfault, missing torch…) instead of "running" forever.
            try:
                event = q.get_nowait()
            except queue_mod.Empty:
                code = training_manager.exit_code(run_id)
                message = f"Training process exited unexpectedly (exit code {code})"
                async with AsyncSessionLocal() as session:
                    r = await session.execute(
                        select(TrainingRun).where(TrainingRun.id == run_id)
                    )
                    rec = r.scalar_one_or_none()
                    if rec and rec.status in ("running", "paused", "pending"):
                        rec.status = "failed"
                        rec.error_message = message
                        rec.completed_at = utcnow()
                        await session.commit()
                        await ws_manager.send(run_id, {"type": "error", "message": message})
                break
        except Exception as exc:
            logger.warning(f"Training queue for {run_id} closed: {exc}")
            break

        await ws_manager.send(run_id, event)
        kind = event.get("type")

        if kind == "epoch_metric":
            await _update_run(run_id, current_epoch=event["epoch"], _append_metric=event)
        elif kind in ("completed", "stopped"):
            fields = {"best_checkpoint_path": event.get("best_checkpoint")}
            if kind == "completed":
                fields.update(status="completed", completed_at=utcnow())
            await _update_run(run_id, **fields)
            break
        elif kind == "error":
            await _update_run(
                run_id, status="failed", error_message=event.get("message"),
                completed_at=utcnow(),
            )
            break

    training_manager.forget(run_id)


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ok = training_manager.pause(run_id)
    if ok:
        run = await _get_run_or_404(run_id, db)
        run.status = "paused"
        await db.commit()
        await ws_manager.send(run_id, {"type": "status", "status": "paused"})
    return {"paused": ok}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ok = training_manager.resume(run_id)
    if ok:
        run = await _get_run_or_404(run_id, db)
        run.status = "running"
        await db.commit()
        await ws_manager.send(run_id, {"type": "status", "status": "running"})
    return {"resumed": ok}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _get_run_or_404(run_id, db)
    if run.status in ("running", "paused", "pending"):
        run.status = "cancelled"
        run.completed_at = utcnow()
        await db.commit()
    # Joining the process can take seconds: never block the event loop on it.
    await asyncio.to_thread(training_manager.stop, run_id)
    return {"stopped": run_id}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _get_run_or_404(run_id, db)
    await asyncio.to_thread(training_manager.cleanup, run_id)
    await asyncio.to_thread(
        shutil.rmtree, settings.models_dir / "trained" / run.id, True
    )
    await db.delete(run)
    await db.commit()
    return {"deleted": run_id}


class ExportRequest(BaseModel):
    format: str = "onnx"


@router.post("/runs/{run_id}/export")
async def export_run(run_id: str, req: ExportRequest, db: AsyncSession = Depends(get_db)):
    run = await _get_run_or_404(run_id, db)
    if req.format not in ("onnx", "safetensors"):
        raise HTTPException(status_code=400, detail="format must be 'onnx' or 'safetensors'")
    if not run.best_checkpoint_path or not Path(run.best_checkpoint_path).exists():
        raise HTTPException(status_code=400, detail="No checkpoint available")

    output_dir = str(settings.models_dir / "trained" / run_id / "export")
    try:
        out_path = await export_model(
            checkpoint_path=run.best_checkpoint_path,
            arch_id=run.architecture,
            arch_config={**(run.arch_config or {}), "_arch_id": run.architecture},
            export_format=req.format,
            output_dir=output_dir,
        )
    except Exception as exc:
        logger.exception("Export failed")
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc
    return {"exported_path": out_path, "format": req.format}


@router.get("/runs/{run_id}/export/download")
async def download_export(run_id: str, format: Optional[str] = None):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No exported model found")
    export_dir = settings.models_dir / "trained" / run_id / "export"
    exts = [format] if format in ("onnx", "safetensors") else ["onnx", "safetensors"]
    for ext in exts:
        candidate = export_dir / f"model.{ext}"
        if candidate.exists():
            return FileResponse(str(candidate), filename=f"model_{run_id}.{ext}")
    raise HTTPException(status_code=404, detail="No exported model found")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dataset_dict(d: Dataset) -> dict:
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
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _run_dict(r: TrainingRun) -> dict:
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
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }
