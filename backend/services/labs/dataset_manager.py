import asyncio
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from core.config import settings

logger = logging.getLogger(__name__)


async def download_huggingface_dataset(
    db_id: str,
    hf_dataset_id: str,
    task_type: str,
    db_session,
) -> None:
    """Downloads a HuggingFace dataset to disk and updates the DB record."""
    from models.dataset import Dataset
    from sqlalchemy import select

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


def _safe_name(filename: Optional[str]) -> Optional[str]:
    """Strip any directory components to prevent path traversal.

    Returns None for empty names, pure paths, or hidden/dotfiles.
    """
    if not filename:
        return None
    name = Path(filename).name  # drops ../ and absolute prefixes
    if not name or name in (".", "..") or name.startswith("."):
        return None
    return name


async def process_upload(
    db_id: str,
    files: list,
    task_type: str,
    db_session,
) -> None:
    """Saves uploaded files and updates the DB record.

    Hardened against path traversal and oversized payloads, and streamed to disk
    in chunks so large uploads don't blow up memory. Always resolves the record
    to a terminal status (ready/error).
    """
    from models.dataset import Dataset
    from sqlalchemy import select

    async def _set_status(**fields):
        async with db_session() as db:
            result = await db.execute(select(Dataset).where(Dataset.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                for k, v in fields.items():
                    setattr(rec, k, v)
                await db.commit()

    max_bytes = settings.max_upload_mb * 1024 * 1024
    dataset_dir = settings.datasets_dir / db_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    num_files = 0
    chunk_size = 1 << 20  # 1 MiB

    try:
        for upload_file in files:
            safe = _safe_name(getattr(upload_file, "filename", None))
            if safe is None:
                continue
            dest = dataset_dir / safe
            with dest.open("wb") as out:
                while True:
                    chunk = await upload_file.read(chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise ValueError(
                            f"Upload exceeds the {settings.max_upload_mb} MB limit"
                        )
                    out.write(chunk)
            num_files += 1

        if num_files == 0:
            raise ValueError("No valid files in upload")

        await _set_status(
            status="ready",
            local_path=str(dataset_dir),
            num_samples=num_files,
            size_bytes=total_bytes,
        )
    except Exception as exc:
        logger.exception("Dataset upload failed: %s", exc)
        await _set_status(status="error", error_message=str(exc))
