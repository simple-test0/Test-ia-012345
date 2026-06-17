import asyncio
import logging
import queue as _queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.websockets.manager import ws_manager
from core.config import settings
from core.database import AsyncSessionLocal, get_db
from hardware.detector import detect_hardware
from models.dataset import Dataset
from models.training_run import TrainingRun
from services.labs.architecture_registry import ARCHITECTURE_REGISTRY, get_arch, list_archs
from services.labs.trainer import training_manager
from services.labs.exporter import export_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/labs", tags=["labs"])


def _spawn(coro) -> asyncio.Task:
    """Fire off a background coroutine, logging any unhandled exception."""
    task = asyncio.create_task(coro)

    def _cb(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            logger.error("Background task failed: %s", t.exception(), exc_info=t.exception())

    task.add_done_callback(_cb)
    return task


def _launch_training(
    run_id: str,
    arch_id: str,
    arch_config: Dict[str, Any],
    training_config: Dict[str, Any],
    dataset_path: Optional[str],
    checkpoint_dir: str,
) -> None:
    """Start the training subprocess and pump its metric queue to the WS + DB.

    A dedicated daemon thread blocks on the (multiprocessing) queue and marshals
    each event back onto the event loop, so we never tie up a shared executor
    thread for the whole run.
    """
    loop = asyncio.get_running_loop()
    q = training_manager.start(
        run_id=run_id,
        arch_id=arch_id,
        arch_config=arch_config,
        training_config=training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )

    async def _handle_event(event: dict) -> bool:
        """Forward an event to the WS + DB. Returns True when terminal."""
        await ws_manager.send(run_id, event)
        etype = event.get("type")
        if etype == "epoch_metric":
            async with AsyncSessionLocal() as session:
                r = await session.execute(select(TrainingRun).where(TrainingRun.id == run_id))
                rec = r.scalar_one_or_none()
                if rec:
                    rec.current_epoch = event["epoch"]
                    rec.status = "running"
                    if rec.started_at is None:
                        rec.started_at = datetime.utcnow()
                    history = list(rec.metrics_history or [])
                    history.append(event)
                    rec.metrics_history = history
                    await session.commit()
        elif etype == "completed":
            async with AsyncSessionLocal() as session:
                r = await session.execute(select(TrainingRun).where(TrainingRun.id == run_id))
                rec = r.scalar_one_or_none()
                if rec:
                    rec.status = "completed"
                    rec.completed_at = datetime.utcnow()
                    rec.best_checkpoint_path = event.get("best_checkpoint")
                    await session.commit()
            return True
        elif etype == "error":
            async with AsyncSessionLocal() as session:
                r = await session.execute(select(TrainingRun).where(TrainingRun.id == run_id))
                rec = r.scalar_one_or_none()
                if rec:
                    rec.status = "failed"
                    rec.error_message = event.get("message")
                    await session.commit()
            return True
        return False

    def _pump() -> None:
        while True:
            try:
                event = q.get(timeout=1.0)
            except _queue.Empty:
                p = training_manager._processes.get(run_id)
                if p and not p.is_alive():
                    break
                continue
            except Exception:
                break

            fut = asyncio.run_coroutine_threadsafe(_handle_event(event), loop)
            try:
                if fut.result(timeout=30):
                    break
            except Exception:
                logger.exception("Failed to handle training event for run %s", run_id)

    threading.Thread(target=_pump, name=f"train-drain-{run_id}", daemon=True).start()


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
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _dataset_dict(ds)


class HFDatasetRequest(BaseModel):
    name: str
    hf_id: str
    task_type: str = "classification"


@router.post("/datasets/huggingface")
async def download_hf_dataset(req: HFDatasetRequest, db: AsyncSession = Depends(get_db)):
    from services.labs.dataset_manager import download_huggingface_dataset

    ds_id = str(uuid.uuid4())
    record = Dataset(
        id=ds_id,
        name=req.name,
        source="huggingface",
        source_identifier=req.hf_id,
        task_type=req.task_type,
        status="downloading",
    )
    db.add(record)
    await db.commit()

    _spawn(download_huggingface_dataset(ds_id, req.hf_id, req.task_type, AsyncSessionLocal))
    return {"id": ds_id, "status": "downloading"}


@router.post("/datasets/upload")
async def upload_dataset(
    name: str = Form(...),
    task_type: str = Form("classification"),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    from services.labs.dataset_manager import process_upload

    ds_id = str(uuid.uuid4())
    record = Dataset(
        id=ds_id,
        name=name,
        source="upload",
        task_type=task_type,
        status="downloading",
    )
    db.add(record)
    await db.commit()

    # Persist while the UploadFile handles are still open (they close once the
    # request returns), then report the terminal status set by process_upload.
    await process_upload(ds_id, files, task_type, AsyncSessionLocal)

    result = await db.execute(select(Dataset).where(Dataset.id == ds_id))
    rec = result.scalar_one_or_none()
    return {"id": ds_id, "status": rec.status if rec else "error"}


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    await db.delete(ds)
    await db.commit()
    return {"deleted": dataset_id}


# ── Training Runs ─────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    name: str
    architecture: str
    arch_config: Dict[str, Any]
    training_config: Dict[str, Any]
    dataset_id: Optional[str] = None


@router.get("/runs")
async def list_runs(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(limit).offset(offset)
    )
    runs = result.scalars().all()
    return [_run_dict(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(run)


@router.post("/runs")
async def create_run(req: CreateRunRequest, db: AsyncSession = Depends(get_db)):
    spec = get_arch(req.architecture)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Architecture '{req.architecture}' not found")

    hw = detect_hardware()
    run_id = str(uuid.uuid4())
    epochs = req.training_config.get("epochs", 10)

    checkpoint_dir = str(settings.models_dir / "trained" / run_id / "checkpoints")

    dataset_path = None
    if req.dataset_id:
        result = await db.execute(select(Dataset).where(Dataset.id == req.dataset_id))  # type: ignore
        from models.dataset import Dataset as DatasetModel
        result = await db.execute(select(DatasetModel).where(DatasetModel.id == req.dataset_id))
        ds = result.scalar_one_or_none()
        if ds and ds.local_path:
            dataset_path = ds.local_path

    run = TrainingRun(
        id=run_id,
        name=req.name,
        status="pending",
        architecture=req.architecture,
        arch_config=req.arch_config,
        training_config=req.training_config,
        dataset_id=req.dataset_id,
        total_epochs=epochs,
        hardware_snapshot={
            "vram_mb": hw.gpus[0].vram_total_mb if hw.gpus else 0,
            "ram_mb": hw.ram_total_mb,
            "cpu_cores": hw.cpu.logical_cores if hw.cpu else 0,
        },
    )
    db.add(run)
    await db.commit()

    _launch_training(
        run_id=run_id,
        arch_id=req.architecture,
        arch_config=req.arch_config,
        training_config=req.training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )

    return {"id": run_id, "status": "running"}


class FinetuneRequest(BaseModel):
    name: Optional[str] = None
    dataset_id: Optional[str] = None
    epochs: Optional[int] = None
    learning_rate: Optional[float] = None
    freeze_backbone: Optional[bool] = None
    training_config: Optional[Dict[str, Any]] = None


@router.post("/runs/{run_id}/finetune")
async def finetune_run(run_id: str, req: FinetuneRequest, db: AsyncSession = Depends(get_db)):
    """Create a new run that continues / reinforces a finished model.

    Warm-starts from the parent's best checkpoint, keeps its architecture, and
    applies fine-tuning defaults (lower LR, fewer epochs) unless overridden.
    """
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    parent = result.scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not parent.best_checkpoint_path:
        raise HTTPException(status_code=400, detail="Parent run has no checkpoint to reinforce")

    # Build the child training config: parent's settings, then fine-tuning
    # defaults, then explicit overrides.
    parent_lr = float(parent.training_config.get("learning_rate", 3e-4))
    tcfg: Dict[str, Any] = dict(parent.training_config or {})
    tcfg.update(req.training_config or {})
    tcfg["init_from"] = parent.best_checkpoint_path
    tcfg["learning_rate"] = req.learning_rate if req.learning_rate is not None else parent_lr * 0.1
    epochs = req.epochs if req.epochs is not None else 5
    tcfg["epochs"] = epochs

    arch_config = dict(parent.arch_config or {})
    if req.freeze_backbone is not None:
        arch_config["freeze_backbone"] = req.freeze_backbone
    # We warm-start from the checkpoint, so skip re-downloading ImageNet weights.
    if parent.architecture == "pretrained":
        arch_config["pretrained"] = False

    dataset_id = req.dataset_id or parent.dataset_id
    dataset_path = None
    if dataset_id:
        ds_res = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
        ds = ds_res.scalar_one_or_none()
        if ds and ds.local_path:
            dataset_path = ds.local_path

    hw = detect_hardware()
    child_id = str(uuid.uuid4())
    checkpoint_dir = str(settings.models_dir / "trained" / child_id / "checkpoints")

    child = TrainingRun(
        id=child_id,
        name=req.name or f"{parent.name} · reinforce",
        status="pending",
        architecture=parent.architecture,
        arch_config=arch_config,
        training_config=tcfg,
        dataset_id=dataset_id,
        total_epochs=epochs,
        hardware_snapshot={
            "vram_mb": hw.gpus[0].vram_total_mb if hw.gpus else 0,
            "ram_mb": hw.ram_total_mb,
            "cpu_cores": hw.cpu.logical_cores if hw.cpu else 0,
            "reinforced_from": run_id,
        },
    )
    db.add(child)
    await db.commit()

    _launch_training(
        run_id=child_id,
        arch_id=parent.architecture,
        arch_config=arch_config,
        training_config=tcfg,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )

    return {"id": child_id, "status": "running", "reinforced_from": run_id}


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ok = training_manager.pause(run_id)
    if ok:
        result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "paused"
            await db.commit()
    return {"paused": ok}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, db: AsyncSession = Depends(get_db)):
    ok = training_manager.resume(run_id)
    if ok:
        result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "running"
            await db.commit()
    return {"resumed": ok}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, db: AsyncSession = Depends(get_db)):
    training_manager.stop(run_id)
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run:
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        await db.commit()
    return {"stopped": run_id}


class ExportRequest(BaseModel):
    format: str = "onnx"


@router.post("/runs/{run_id}/export")
async def export_run(run_id: str, req: ExportRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.best_checkpoint_path:
        raise HTTPException(status_code=400, detail="No checkpoint available")

    output_dir = str(settings.models_dir / "trained" / run_id / "export")
    out_path = await export_model(
        checkpoint_path=run.best_checkpoint_path,
        arch_id=run.architecture,
        arch_config=run.arch_config,
        export_format=req.format,
        output_dir=output_dir,
    )
    return {"exported_path": out_path, "format": req.format}


@router.get("/runs/{run_id}/export/download")
async def download_export(run_id: str):
    export_dir = settings.models_dir / "trained" / run_id / "export"
    for ext in ["onnx", "safetensors"]:
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
