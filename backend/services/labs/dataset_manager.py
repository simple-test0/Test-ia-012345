import asyncio
import logging

from core.config import settings

logger = logging.getLogger(__name__)


async def download_huggingface_dataset(
    db_id: str,
    hf_dataset_id: str,
    task_type: str,
    db_session,
) -> None:
    """Downloads a HuggingFace dataset to disk and updates the DB record."""
    from sqlalchemy import select

    from models.dataset import Dataset

    dataset_dir = settings.datasets_dir / db_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    async def _update_status(status: str, error: str = "", path: str = "", num_samples: int = 0):
        async with db_session() as db:
            result = await db.execute(select(Dataset).where(Dataset.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                if error:
                    rec.error_message = error
                if path:
                    rec.local_path = path
                if num_samples:
                    rec.num_samples = num_samples
                await db.commit()

    try:
        def _download():
            from datasets import load_dataset
            ds = load_dataset(hf_dataset_id)
            ds.save_to_disk(str(dataset_dir))
            total = sum(len(split) for split in ds.values())
            return total

        num_samples = await asyncio.get_event_loop().run_in_executor(None, _download)
        await _update_status("ready", path=str(dataset_dir), num_samples=num_samples)
    except Exception as exc:
        logger.exception(f"HuggingFace download failed: {exc}")
        await _update_status("error", error=str(exc))


async def process_upload(
    db_id: str,
    files: list,
    task_type: str,
    db_session,
) -> None:
    """Persist uploaded file contents and update the DB record.

    `files` is a list of (filename, content-bytes) tuples: the route reads the
    UploadFile objects before responding, because Starlette closes them as
    soon as the request handler returns — a background task reading them
    afterwards would hit closed files.
    """
    from pathlib import Path

    from sqlalchemy import select

    from models.dataset import Dataset

    async def _update(status: str, error: str = "", **fields) -> None:
        async with db_session() as db:
            result = await db.execute(select(Dataset).where(Dataset.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                if error:
                    rec.error_message = error
                for k, v in fields.items():
                    setattr(rec, k, v)
                await db.commit()

    try:
        dataset_dir = settings.datasets_dir / db_id
        dataset_dir.mkdir(parents=True, exist_ok=True)

        total_bytes = 0
        num_files = 0
        for filename, content in files:
            # Path(...).name strips any directory components a client could
            # smuggle in ("../../x") so files always land inside dataset_dir.
            safe_name = Path(filename or "").name or f"file_{num_files}"
            (dataset_dir / safe_name).write_bytes(content)
            total_bytes += len(content)
            num_files += 1

        await _update(
            "ready",
            local_path=str(dataset_dir),
            num_samples=num_files,
            size_bytes=total_bytes,
        )
    except Exception as exc:
        logger.exception(f"Dataset upload processing failed: {exc}")
        await _update("error", error=str(exc))
