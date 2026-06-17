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
    """Saves uploaded files and updates the DB record."""
    from sqlalchemy import select

    from models.dataset import Dataset

    dataset_dir = settings.datasets_dir / db_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    num_files = 0

    for upload_file in files:
        dest = dataset_dir / upload_file.filename
        content = await upload_file.read()
        dest.write_bytes(content)
        total_bytes += len(content)
        num_files += 1

    async with db_session() as db:
        result = await db.execute(select(Dataset).where(Dataset.id == db_id))
        rec = result.scalar_one_or_none()
        if rec:
            rec.status = "ready"
            rec.local_path = str(dataset_dir)
            rec.num_samples = num_files
            rec.size_bytes = total_bytes
            await db.commit()
