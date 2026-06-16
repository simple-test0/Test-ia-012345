import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from services.labs.architecture_registry import ARCHITECTURE_REGISTRY, get_arch, list_archs
from services.labs.trainer import training_manager
from services.labs.exporter import export_model

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
    files: List[UploadFile] = File(...),
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
async def list_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TrainingRun).order_by(TrainingRun.created_at.desc()))
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

    # Start training subprocess
    q = training_manager.start(
        run_id=run_id,
        arch_id=req.architecture,
        arch_config=req.arch_config,
        training_config=req.training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
    )

    # Background task to drain subprocess queue → WS
    import asyncio
    from api.websockets.manager import ws_manager

    async def _drain_queue():
        from sqlalchemy import select as sel
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=1.0)
                )
            except Exception:
                p = training_manager._processes.get(run_id)
                if p and not p.is_alive():
                    break
                continue

            await ws_manager.send(run_id, event)

            # Persist epoch metrics to DB
            if event.get("type") == "epoch_metric":
                async with AsyncSessionLocal() as session:
                    r = await session.execute(sel(TrainingRun).where(TrainingRun.id == run_id))
                    rec = r.scalar_one_or_none()
                    if rec:
                        rec.current_epoch = event["epoch"]
                        rec.status = "running"
                        history = list(rec.metrics_history or [])
                        history.append(event)
                        rec.metrics_history = history
                        await session.commit()

            elif event.get("type") == "completed":
                async with AsyncSessionLocal() as session:
                    r = await session.execute(sel(TrainingRun).where(TrainingRun.id == run_id))
                    rec = r.scalar_one_or_none()
                    if rec:
                        rec.status = "completed"
                        rec.completed_at = datetime.utcnow()
                        rec.best_checkpoint_path = event.get("best_checkpoint")
                        await session.commit()
                break

            elif event.get("type") == "error":
                async with AsyncSessionLocal() as session:
                    r = await session.execute(sel(TrainingRun).where(TrainingRun.id == run_id))
                    rec = r.scalar_one_or_none()
                    if rec:
                        rec.status = "failed"
                        rec.error_message = event.get("message")
                        await session.commit()
                break

    asyncio.create_task(_drain_queue())

    return {"id": run_id, "status": "running"}


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
