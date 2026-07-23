import uuid
from datetime import datetime
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
from models.tokenizer_model import TokenizerModel
from models.training_run import TrainingRun
from services.labs.architecture_registry import get_arch, list_archs
from services.labs.exporter import export_model
from services.labs.tokenizer_manager import ALGORITHMS, DEFAULT_SPECIAL_TOKENS, encode_preview
from services.labs.trainer import training_manager
from services.labs.training_options import OPTION_GROUPS, TRAINING_OPTIONS

router = APIRouter(prefix="/labs", tags=["labs"])

# Keep strong references to fire-and-forget tasks: asyncio only holds weak
# refs, so an unreferenced task can be garbage-collected mid-flight.
_background_tasks: set = set()


def _track_task(task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ── Architectures ─────────────────────────────────────────────────────────────

@router.get("/training-options")
async def get_training_options():
    return {"options": TRAINING_OPTIONS, "groups": OPTION_GROUPS}


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

    _track_task(
        asyncio.create_task(
            download_huggingface_dataset(ds_id, req.hf_id, req.task_type, AsyncSessionLocal)
        )
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

    # Read the payloads now: Starlette closes UploadFile objects when this
    # handler returns, so a background task can't read them afterwards.
    contents = [(f.filename, await f.read()) for f in files]

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

    _track_task(
        asyncio.create_task(process_upload(ds_id, contents, task_type, AsyncSessionLocal))
    )
    return {"id": ds_id, "status": "processing"}


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    import shutil
    from pathlib import Path

    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Free the disk too — but only paths under our datasets directory.
    if ds.local_path:
        path = Path(ds.local_path).resolve()
        if path.is_relative_to(settings.datasets_dir.resolve()):
            shutil.rmtree(path, ignore_errors=True)

    await db.delete(ds)
    await db.commit()
    return {"deleted": dataset_id}


# ── Tokenizers ────────────────────────────────────────────────────────────────

@router.get("/tokenizers/algorithms")
async def get_tokenizer_algorithms():
    return {
        "algorithms": [{"id": k, **v} for k, v in ALGORITHMS.items()],
        "default_special_tokens": DEFAULT_SPECIAL_TOKENS,
    }


@router.get("/tokenizers")
async def list_tokenizers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TokenizerModel).order_by(TokenizerModel.created_at.desc())
    )
    return [_tokenizer_dict(t) for t in result.scalars().all()]


@router.get("/tokenizers/{tokenizer_id}")
async def get_tokenizer(tokenizer_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TokenizerModel).where(TokenizerModel.id == tokenizer_id)
    )
    tok = result.scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=404, detail="Tokenizer not found")
    return _tokenizer_dict(tok)


class TrainTokenizerRequest(BaseModel):
    name: str
    dataset_id: str
    algorithm: str = "bpe"
    vocab_size: int = 8192
    min_frequency: int = 2
    lowercase: bool = False
    byte_level: bool = True
    special_tokens: Optional[List[str]] = None


@router.post("/tokenizers")
async def train_tokenizer_route(req: TrainTokenizerRequest, db: AsyncSession = Depends(get_db)):
    import asyncio

    from services.labs.tokenizer_manager import train_tokenizer

    if req.algorithm not in ALGORITHMS:
        raise HTTPException(status_code=422, detail=f"Algorithme inconnu: {req.algorithm}")
    if not (16 <= req.vocab_size <= 200_000):
        raise HTTPException(status_code=422, detail="vocab_size doit être entre 16 et 200000")

    result = await db.execute(select(Dataset).where(Dataset.id == req.dataset_id))
    ds = result.scalar_one_or_none()
    if ds is None or ds.status != "ready" or not ds.local_path:
        raise HTTPException(status_code=400, detail="Dataset introuvable ou pas prêt")

    tok_id = str(uuid.uuid4())
    record = TokenizerModel(
        id=tok_id,
        name=req.name,
        algorithm=req.algorithm,
        vocab_size=req.vocab_size,
        min_frequency=req.min_frequency,
        lowercase=req.lowercase,
        byte_level=req.byte_level,
        special_tokens=req.special_tokens or DEFAULT_SPECIAL_TOKENS,
        dataset_id=req.dataset_id,
        status="training",
    )
    db.add(record)
    await db.commit()

    _track_task(
        asyncio.create_task(
            train_tokenizer(
                tok_id,
                req.algorithm,
                req.vocab_size,
                req.min_frequency,
                req.special_tokens,
                req.lowercase,
                req.byte_level,
                ds.local_path,
                AsyncSessionLocal,
            )
        )
    )
    return {"id": tok_id, "status": "training"}


class EncodeRequest(BaseModel):
    text: str


@router.post("/tokenizers/{tokenizer_id}/encode")
async def encode_with_tokenizer(
    tokenizer_id: str, req: EncodeRequest, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TokenizerModel).where(TokenizerModel.id == tokenizer_id)
    )
    tok = result.scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=404, detail="Tokenizer not found")
    if tok.status != "ready" or not tok.local_path:
        raise HTTPException(status_code=400, detail="Tokenizer pas encore prêt")
    if len(req.text) > 10_000:
        raise HTTPException(status_code=422, detail="Texte trop long pour la prévisualisation")
    import asyncio

    return await asyncio.get_event_loop().run_in_executor(
        None, encode_preview, tok.local_path, req.text
    )


@router.delete("/tokenizers/{tokenizer_id}")
async def delete_tokenizer(tokenizer_id: str, db: AsyncSession = Depends(get_db)):
    import shutil
    from pathlib import Path

    result = await db.execute(
        select(TokenizerModel).where(TokenizerModel.id == tokenizer_id)
    )
    tok = result.scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=404, detail="Tokenizer not found")

    if tok.local_path:
        path = Path(tok.local_path).resolve().parent
        if path.is_relative_to(settings.tokenizers_dir.resolve()):
            shutil.rmtree(path, ignore_errors=True)

    await db.delete(tok)
    await db.commit()
    return {"deleted": tokenizer_id}


# ── Training Runs ─────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    name: str
    architecture: str
    arch_config: Dict[str, Any]
    training_config: Dict[str, Any]
    dataset_id: Optional[str] = None
    tokenizer_id: Optional[str] = None


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
        result = await db.execute(select(Dataset).where(Dataset.id == req.dataset_id))
        ds = result.scalar_one_or_none()
        if ds and ds.local_path:
            dataset_path = ds.local_path

    tokenizer_path = None
    arch_config = dict(req.arch_config)
    if req.tokenizer_id:
        result = await db.execute(
            select(TokenizerModel).where(TokenizerModel.id == req.tokenizer_id)
        )
        tok = result.scalar_one_or_none()
        if tok is None or tok.status != "ready" or not tok.local_path:
            raise HTTPException(status_code=400, detail="Tokenizer introuvable ou pas prêt")
        tokenizer_path = tok.local_path
        # The embedding table must match the tokenizer's real vocabulary.
        if tok.actual_vocab_size and "vocab_size" in arch_config:
            arch_config["vocab_size"] = tok.actual_vocab_size

    run = TrainingRun(
        id=run_id,
        name=req.name,
        status="pending",
        architecture=req.architecture,
        arch_config=arch_config,
        training_config=req.training_config,
        dataset_id=req.dataset_id,
        tokenizer_id=req.tokenizer_id,
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
        arch_config=arch_config,
        training_config=req.training_config,
        dataset_path=dataset_path,
        checkpoint_dir=checkpoint_dir,
        tokenizer_path=tokenizer_path,
    )

    # Background task to drain subprocess queue → WS
    import asyncio

    from api.websockets.manager import ws_manager

    async def _drain_queue():
        from sqlalchemy import select as sel
        finished = False
        while True:
            try:
                event = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: q.get(timeout=1.0)
                )
            except Exception:
                if not training_manager.is_alive(run_id):
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
                finished = True
                break

            elif event.get("type") == "error":
                async with AsyncSessionLocal() as session:
                    r = await session.execute(sel(TrainingRun).where(TrainingRun.id == run_id))
                    rec = r.scalar_one_or_none()
                    if rec:
                        rec.status = "failed"
                        rec.error_message = event.get("message")
                        await session.commit()
                finished = True
                break

        if not finished:
            # The subprocess died without a terminal event (crash, OOM kill,
            # user stop) — don't leave the run showing "running" forever.
            async with AsyncSessionLocal() as session:
                r = await session.execute(sel(TrainingRun).where(TrainingRun.id == run_id))
                rec = r.scalar_one_or_none()
                if rec and rec.status in ("pending", "running", "paused"):
                    rec.status = "failed"
                    rec.error_message = "Le processus d'entraînement s'est arrêté de façon inattendue"
                    rec.completed_at = datetime.utcnow()
                    await session.commit()
                    await ws_manager.send(
                        run_id, {"type": "error", "message": rec.error_message}
                    )

        # Reap the subprocess and drop its queue/events from memory.
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: training_manager.cleanup(run_id)
        )

    _track_task(asyncio.create_task(_drain_queue()))

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
    import asyncio

    # stop() joins the subprocess (up to ~10s) — keep that off the event loop.
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: training_manager.stop(run_id)
    )
    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run and run.status in ("pending", "running", "paused"):
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        await db.commit()
    return {"stopped": run_id}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)):
    import asyncio
    import shutil

    result = await db.execute(select(TrainingRun).where(TrainingRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("pending", "running", "paused"):
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: training_manager.stop(run_id)
        )

    run_dir = (settings.models_dir / "trained" / run_id).resolve()
    if run_dir.is_relative_to((settings.models_dir / "trained").resolve()):
        shutil.rmtree(run_dir, ignore_errors=True)

    await db.delete(run)
    await db.commit()
    return {"deleted": run_id}


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
    try:
        out_path = await export_model(
            checkpoint_path=run.best_checkpoint_path,
            arch_id=run.architecture,
            arch_config=run.arch_config,
            export_format=req.format,
            output_dir=output_dir,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
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

def _tokenizer_dict(t: TokenizerModel) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "algorithm": t.algorithm,
        "vocab_size": t.vocab_size,
        "actual_vocab_size": t.actual_vocab_size,
        "min_frequency": t.min_frequency,
        "lowercase": t.lowercase,
        "byte_level": t.byte_level,
        "special_tokens": t.special_tokens,
        "dataset_id": t.dataset_id,
        "stats": t.stats,
        "status": t.status,
        "error_message": t.error_message,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


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
        "tokenizer_id": r.tokenizer_id,
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
