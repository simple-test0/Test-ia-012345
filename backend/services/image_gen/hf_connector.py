import asyncio
import logging
import shutil
from pathlib import Path
from typing import List

from core.config import settings

logger = logging.getLogger(__name__)


def _token():
    return settings.huggingface_token or None


def _repo_cache_path(repo_id: str) -> Path:
    """Path where snapshot_download stores a repo under our cache_dir."""
    folder = "models--" + repo_id.replace("/", "--")
    return settings.models_dir / "diffusion" / folder


def dir_size_bytes(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except Exception:
        return 0


def _estimate_download_bytes(siblings) -> int:
    """Estimate the bytes diffusers will pull for a repo.

    Mirrors the fp16-variant preference in `_fetch`: count fp16 safetensors if
    present, else plain safetensors, else everything. Non-weight files (configs,
    tokenizers) are always included. Best effort — falls back to summing all
    files when sizes are missing.
    """
    def size(s) -> int:
        return getattr(s, "size", None) or 0

    def name(s) -> str:
        return getattr(s, "rfilename", "") or ""

    weights = [s for s in siblings if name(s).endswith((".safetensors", ".bin"))]
    others = sum(size(s) for s in siblings if s not in weights)

    fp16 = [s for s in weights if ".fp16." in name(s)]
    safet = [s for s in weights if name(s).endswith(".safetensors") and ".fp16." not in name(s)]
    if fp16:
        chosen = fp16
    elif safet:
        chosen = safet
    else:
        chosen = weights
    return others + sum(size(s) for s in chosen)


def download_progress(repo_id: str, total_bytes: int) -> int:
    """Coarse 0-100 progress for an in-flight download (best effort)."""
    if total_bytes <= 0:
        return 0
    current = dir_size_bytes(_repo_cache_path(repo_id))
    return max(0, min(99, int(current * 100 / total_bytes)))


# Weights we actually load are fp16 safetensors (2 bytes/param), so we estimate
# the on-disk download size from the parameter count rather than summing every
# redundant variant a repo may ship.
_BYTES_PER_PARAM_FP16 = 2


def _param_count(model) -> int:
    """Total parameter count from a model's safetensors metadata (0 if unknown)."""
    st = getattr(model, "safetensors", None)
    if st is None:
        return 0
    total = getattr(st, "total", None)
    if total:
        return int(total)
    params = getattr(st, "parameters", None)
    if isinstance(params, dict):
        return int(sum(params.values()))
    return 0


def search_hf_models(query: str, limit: int = 25) -> List[dict]:
    """Search Hugging Face for text-to-image diffusers models.

    Synchronous (uses huggingface_hub HTTP). Call via run_in_executor.
    Each result includes the parameter count and an estimated download size so
    the UI can show how heavy a model is before the user commits to it.
    """
    from huggingface_hub import HfApi

    api = HfApi(token=_token())

    common = dict(
        search=query,
        filter="diffusers",
        pipeline_tag="text-to-image",
        sort="downloads",
        direction=-1,
        limit=limit,
    )
    # `expand=[...]` lets us fetch safetensors metadata (parameter counts).
    # Older huggingface_hub versions don't support it, so fall back to `full`.
    try:
        models = api.list_models(
            expand=["downloads", "likes", "gated", "pipeline_tag", "tags", "safetensors"],
            **common,
        )
    except (TypeError, ValueError):
        models = api.list_models(full=True, **common)

    results = []
    for m in models:
        params = _param_count(m)
        results.append(
            {
                "repo_id": m.id,
                "name": m.id.split("/")[-1],
                "downloads": getattr(m, "downloads", 0) or 0,
                "likes": getattr(m, "likes", 0) or 0,
                "gated": bool(getattr(m, "gated", False)),
                "pipeline_tag": getattr(m, "pipeline_tag", None),
                "tags": list(getattr(m, "tags", None) or []),
                "params": params,
                # Estimated fp16 download size; 0 when the param count is unknown.
                "size_bytes": params * _BYTES_PER_PARAM_FP16 if params else 0,
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
        def _probe():
            from huggingface_hub import model_info

            meta = {
                "gated": False, "pipeline_class": None, "tags": None,
                "downloads": 0, "likes": 0, "total_bytes": 0,
            }
            try:
                info = model_info(repo_id, token=_token(), files_metadata=True)
                meta["gated"] = bool(getattr(info, "gated", False))
                meta["tags"] = list(getattr(info, "tags", None) or [])
                meta["downloads"] = getattr(info, "downloads", 0) or 0
                meta["likes"] = getattr(info, "likes", 0) or 0
                card = getattr(info, "cardData", None) or {}
                meta["pipeline_class"] = card.get("pipeline_tag") if isinstance(card, dict) else None
                # Estimate only the files we'll actually pull (fp16 safetensors +
                # configs), not every redundant variant in the repo, so the
                # progress denominator matches what lands on disk.
                meta["total_bytes"] = _estimate_download_bytes(
                    getattr(info, "siblings", None) or []
                )
            except Exception:
                pass

            # Refuse to start if free disk is clearly insufficient.
            free = shutil.disk_usage(str(diffusion_dir)).free
            needed = max(int(meta["total_bytes"] * 1.1), settings.min_free_disk_mb * 1024 * 1024)
            if meta["total_bytes"] and free < needed:
                raise RuntimeError(
                    f"Insufficient disk space: need ~{needed // (1024*1024)}MB, "
                    f"have {free // (1024*1024)}MB free."
                )
            return meta

        meta = await asyncio.get_event_loop().run_in_executor(None, _probe)
        # Persist metadata + estimated total so the status endpoint can report progress.
        await _update("downloading", **meta)

        def _fetch():
            # Use diffusers' own downloader so only the components a text-to-image
            # pipeline needs are pulled — and prefer the fp16 safetensors variant.
            # A bare snapshot_download grabs *every* variant (fp16 + fp32 + .bin +
            # onnx…), which can balloon a single SDXL repo past 20GB.
            from diffusers import DiffusionPipeline

            # No `revision` -> always pulls the latest `main` snapshot.
            common = dict(cache_dir=str(diffusion_dir), token=_token())
            attempts = (
                dict(variant="fp16", use_safetensors=True),  # smallest: fp16 only
                dict(use_safetensors=True),                  # repo has no fp16 variant
                dict(),                                       # last resort: .bin weights
            )
            path = None
            last_exc = None
            for kwargs in attempts:
                try:
                    path = DiffusionPipeline.download(repo_id, **kwargs, **common)
                    break
                except Exception as exc:  # variant/format not available -> try next
                    last_exc = exc
            if path is None:
                raise last_exc or RuntimeError("Download failed")
            return {"local_path": path, "size_bytes": dir_size_bytes(Path(path))}

        result = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        await _update("ready", **result)

    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "gated" in lowered or "401" in lowered or "403" in lowered or "access" in lowered:
            message = (
                "Gated model — set HUGGINGFACE_TOKEN in .env and accept the license "
                f"on https://huggingface.co/{repo_id}"
            )
        logger.exception(f"HuggingFace model download failed for {repo_id}: {exc}")
        await _update("error", error_message=message, gated=("gated" in lowered))
