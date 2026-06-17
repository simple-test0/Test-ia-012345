import asyncio
import logging
from pathlib import Path
from typing import List

from core.config import settings

logger = logging.getLogger(__name__)


def _token():
    return settings.huggingface_token or None


def search_hf_models(query: str, limit: int = 25) -> List[dict]:
    """Search Hugging Face for text-to-image diffusers models.

    Synchronous (uses huggingface_hub HTTP). Call via run_in_executor.
    """
    from huggingface_hub import HfApi

    api = HfApi(token=_token())
    models = api.list_models(
        search=query,
        filter="diffusers",
        pipeline_tag="text-to-image",
        sort="downloads",
        direction=-1,
        limit=limit,
        full=True,
    )

    results = []
    for m in models:
        results.append(
            {
                "repo_id": m.id,
                "name": m.id.split("/")[-1],
                "downloads": getattr(m, "downloads", 0) or 0,
                "likes": getattr(m, "likes", 0) or 0,
                "gated": bool(getattr(m, "gated", False)),
                "pipeline_tag": getattr(m, "pipeline_tag", None),
                "tags": list(getattr(m, "tags", None) or []),
            }
        )
    return results


async def download_hf_model(db_id: str, repo_id: str, db_session) -> None:
    """Download a HF diffusion model to disk and update the DB record.

    Mirrors services.labs.dataset_manager.download_huggingface_dataset.
    """
    from sqlalchemy import select

    from models.diffusion_model import DiffusionModel

    diffusion_dir = settings.models_dir / "diffusion"
    diffusion_dir.mkdir(parents=True, exist_ok=True)

    async def _update(status: str, **fields) -> None:
        async with db_session() as db:
            result = await db.execute(
                select(DiffusionModel).where(DiffusionModel.id == db_id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                for k, v in fields.items():
                    if v is not None:
                        setattr(rec, k, v)
                await db.commit()

    try:
        def _download():
            from huggingface_hub import model_info, snapshot_download

            gated = False
            pipeline_class = None
            tags = None
            downloads = 0
            likes = 0
            try:
                info = model_info(repo_id, token=_token())
                gated = bool(getattr(info, "gated", False))
                tags = list(getattr(info, "tags", None) or [])
                downloads = getattr(info, "downloads", 0) or 0
                likes = getattr(info, "likes", 0) or 0
                card = getattr(info, "cardData", None) or {}
                pipeline_class = card.get("pipeline_tag") if isinstance(card, dict) else None
            except Exception:
                pass

            # No `revision` -> always pulls the latest `main` snapshot.
            path = snapshot_download(
                repo_id=repo_id,
                cache_dir=str(diffusion_dir),
                token=_token(),
            )

            size_bytes = sum(
                f.stat().st_size for f in Path(path).rglob("*") if f.is_file()
            )
            return {
                "local_path": path,
                "size_bytes": size_bytes,
                "gated": gated,
                "pipeline_class": pipeline_class,
                "tags": tags,
                "downloads": downloads,
                "likes": likes,
            }

        meta = await asyncio.get_event_loop().run_in_executor(None, _download)
        await _update("ready", **meta)

    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "gated" in lowered or "401" in lowered or "403" in lowered or "access" in lowered:
            message = (
                "Gated model — set HUGGINGFACE_TOKEN in .env and accept the license "
                f"on https://huggingface.co/{repo_id}"
            )
        logger.exception(f"HuggingFace model download failed for {repo_id}: {exc}")
        await _update("error", error_message=message, gated=True if "gated" in lowered else None)
