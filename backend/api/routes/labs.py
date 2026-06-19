import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal, get_db
from hardware.detector import detect_hardware
from models.dataset import Dataset
from models.training_run import TrainingRun
from schemas import serialize_dataset, serialize_run
from services.labs.architecture_registry import get_arch, list_archs
from services.labs.exporter import export_model
from services.labs.trainer import training_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/labs", tags=["labs"])


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
async def list_datasets(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dataset).order_by(Dataset.created_at.desc()).limit(limit).offset(offset)
    )
    datasets = result.scalars().all()
    return [serialize_dataset(d) for d in datasets]


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return serialize_dataset(ds)


class HFDatasetRequest(BaseModel):
    name: str
    hf_id: str
    task_type: str = "classification"


@router.post("/datasets/huggingface")
async def download_hf_dataset(req: HFDatasetRequest, db: AsyncSession = Depends(get_db)):
    import asyncio

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

    asyncio.create_task(
        download_huggingface_dataset(ds_id, req.hf_id, req.task_type, AsyncSessionLocal)
    )
    return {"id": ds_id, "status": "downloading"}


@router.post("/datasets/upload")
async def upload_dataset(
    name: str = Form(...),
    task_type: str = Form("classification"),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    import asyncio

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

    asyncio.create_task(process_upload(ds_id, files, task_type, AsyncSessionLocal))
    return {"id": ds_id, "status": "processing"}


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Dissociate any training runs that referenced this dataset so they are not
    # left pointing at a non-existent id (dataset_id is a plain column, not a
    # DB-level FK — SQLite makes ON DELETE migrations heavy).
    runs = await db.execute(select(TrainingRun).where(TrainingRun.dataset_id == dataset_id))
    for run in runs.scalars().all():
        run.dataset_id = None

    await db.delete(ds)
    await db.commit()
    return {"deleted": dataset_id}


# ── Training Runs ─────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    name: str
    architecture: str
    arch_config: dict[str, Any]
    training_config: dict[str, Any]
    dataset_id: str | None = None


@router.get("/runs")
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(limit).offset(offset)
    )
    runs = result.scalars().all()
    return [serialize_run(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return serialize_run(run)


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
        result = await db.execute(select(Dataset).where(Dataset.id == req.dataset_id))
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

    # Start training subprocess (registers the metric queue in training_manager).
    training_manager.start(
        run_id=run_id,
        arch_id=req.architecture,
        arch_config=req.arch_config,
        training_config=req.training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )

    # Background task to drain subprocess queue → WS
    import asyncio

    asyncio.create_task(_drain_queue(run_id))

    return {"id": run_id, "status": "running"}


async def _update_run(run_id: str, **fields) -> None:
    """Apply a partial update to a TrainingRun in its own short-lived session.

    `metrics_history_append` is a special key: the event dict to append to the
    run's metrics history (the column is JSON, so we must reassign the list).
    """
    append_event = fields.pop("metrics_history_append", None)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TrainingRun).where(TrainingRun.id == run_id))
        rec = result.scalar_one_or_none()
        if rec is None:
            return
        for key, value in fields.items():
            setattr(rec, key, value)
        if append_event is not None:
            rec.metrics_history = list(rec.metrics_history or []) + [append_event]
        await session.commit()


async def _drain_queue(run_id: str) -> None:
    """Forward subprocess metric-queue events to the WS and persist key ones.

    Runs as a fire-and-forget task; any unexpected error is logged and a final
    `error` event is emitted so the run does not appear stuck as "running".
    """
    import asyncio
    import queue

    from api.websockets.manager import ws_manager

    q = training_manager.get_queue(run_id)
    if q is None:
        return
    try:
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=1.0)
                )
            except queue.Empty:
                p = training_manager._processes.get(run_id)
                if p and not p.is_alive():
                    break
                continue

            await ws_manager.send(run_id, event)
            etype = event.get("type")

            if etype == "epoch_metric":
                fields = {
                    "current_epoch": event["epoch"],
                    "status": "running",
                    "metrics_history_append": event,
                }
                # Stamp the start time once, on the first epoch.
                if event.get("epoch") == 1:
                    fields["started_at"] = datetime.now(UTC)
                await _update_run(run_id, **fields)

            elif etype == "completed":
                await _update_run(
                    run_id,
                    status="completed",
                    completed_at=datetime.now(UTC),
                    best_checkpoint_path=event.get("best_checkpoint"),
                )
                break

            elif etype == "error":
                await _update_run(
                    run_id,
                    status="failed",
                    error_message=event.get("message"),
                )
                break
    except Exception as exc:
        logger.exception("Training drain loop failed for run %s", run_id)
        with contextlib.suppress(Exception):
            await ws_manager.send(run_id, {"type": "error", "message": str(exc)})
        await _update_run(run_id, status="failed", error_message=str(exc))


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
        run.completed_at = datetime.now(UTC)
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


