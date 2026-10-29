import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import List

from fastapi import UploadFile

from core.config import settings

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


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

    async def _update_status(status: str, error: str = "", path: str = "", **fields) -> None:
        async with db_session() as db:
            result = await db.execute(select(Dataset).where(Dataset.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                if error:
                    rec.error_message = error
                if path:
                    rec.local_path = path
                for k, v in fields.items():
                    if v:
                        setattr(rec, k, v)
                await db.commit()

    try:
        def _download():
            from datasets import load_dataset

            ds = load_dataset(hf_dataset_id, token=settings.huggingface_token or None)
            ds.save_to_disk(str(dataset_dir))
            total = sum(len(split) for split in ds.values())
            num_classes, class_names = 0, None
            first = next(iter(ds.values()), None)
            if first is not None:
                for col in ("label", "labels", "target"):
                    feat = first.features.get(col)
                    names = getattr(feat, "names", None)
                    if names:
                        num_classes, class_names = len(names), list(names)
                        break
            return total, num_classes, class_names, _dir_size(dataset_dir)

        total, num_classes, class_names, size = await asyncio.to_thread(_download)
        await _update_status(
            "ready", path=str(dataset_dir), num_samples=total,
            num_classes=num_classes, class_names=class_names, size_bytes=size,
        )
    except Exception as exc:
        logger.exception(f"HuggingFace download failed: {exc}")
        shutil.rmtree(dataset_dir, ignore_errors=True)
        await _update_status("error", error=_friendly(str(exc), hf_dataset_id))


def _friendly(message: str, dataset_id: str) -> str:
    low = message.lower()
    if "doesn't exist" in low or "not found" in low or "404" in low:
        return f"Dataset '{dataset_id}' not found on Hugging Face (format: 'owner/name' or 'mnist')."
    if "gated" in low or "401" in low or "403" in low:
        return (
            f"Dataset '{dataset_id}' is gated — set HUGGINGFACE_TOKEN in backend/.env "
            "and accept its terms on huggingface.co."
        )
    return message


def _dir_size(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def safe_filename(name: str) -> str:
    """Strip directories and odd characters from a client-supplied file name
    (prevents writing outside the dataset folder via '../')."""
    name = Path((name or "").replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" .")
    return name[:200] or "file"


async def save_uploads(dataset_dir: Path, files: List[UploadFile]) -> tuple:
    """Stream uploaded files to disk (never fully in memory).

    Must run inside the request: FastAPI closes UploadFiles once the response
    is sent, so a background task cannot read them.
    Returns (num_files, total_bytes). Raises ValueError when too large.
    """
    dataset_dir.mkdir(parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    total = 0
    count = 0
    used = set()
    for upload in files:
        name = safe_filename(upload.filename)
        stem, suffix, n = Path(name).stem, Path(name).suffix, 1
        while name in used:  # same name twice in one upload: keep both
            name = f"{stem}_{n}{suffix}"
            n += 1
        used.add(name)
        dest = dataset_dir / name
        with open(dest, "wb") as out:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(
                        f"Upload exceeds the {settings.max_upload_mb} MB limit (MAX_UPLOAD_MB)."
                    )
                await asyncio.to_thread(out.write, chunk)
        count += 1
    return count, total
