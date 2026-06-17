import asyncio
import base64
import io
import logging
from collections import OrderedDict
from typing import Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)


# Map UI sampler names to diffusers scheduler classes (+ optional config kwargs).
_SAMPLER_MAP = {
    "DPM++ 2M": ("DPMSolverMultistepScheduler", {"algorithm_type": "dpmsolver++"}),
    "Euler": ("EulerDiscreteScheduler", {}),
    "Euler a": ("EulerAncestralDiscreteScheduler", {}),
    "DDIM": ("DDIMScheduler", {}),
    "LMS": ("LMSDiscreteScheduler", {}),
}


def apply_sampler(pipe, sampler: str) -> None:
    """Swap the pipeline scheduler to match the requested sampler.

    Best-effort: some pipelines (e.g. FLUX) use fixed schedulers, so failures
    are logged and ignored rather than aborting generation.
    """
    entry = _SAMPLER_MAP.get(sampler)
    if not entry:
        return
    cls_name, extra = entry
    try:
        import diffusers

        scheduler_cls = getattr(diffusers, cls_name, None)
        if scheduler_cls is None or not hasattr(pipe, "scheduler"):
            return
        pipe.scheduler = scheduler_cls.from_config(pipe.scheduler.config, **extra)
        logger.info(f"Applied sampler {sampler} -> {cls_name}")
    except Exception as exc:
        logger.info(f"Could not apply sampler {sampler}: {exc}")


class PipelineManager:
    def __init__(self, max_loaded: int = 1):
        self._max_loaded = max_loaded
        self._loaded: OrderedDict = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_pipeline(self, model_id: str, repo_id: str):
        async with self._lock:
            if model_id in self._loaded:
                self._loaded.move_to_end(model_id)
                return self._loaded[model_id]

            if len(self._loaded) >= self._max_loaded:
                oldest_id, oldest_pipe = self._loaded.popitem(last=False)
                logger.info(f"Evicting pipeline: {oldest_id}")
                del oldest_pipe
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass

            pipe = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._load_pipeline(model_id, repo_id)
            )
            self._loaded[model_id] = pipe
            return pipe

    def _load_pipeline(self, model_id: str, repo_id: str):
        import torch
        from diffusers import AutoPipelineForText2Image

        from core.config import settings

        vram_mb = self._get_vram_mb()
        dtype = torch.float16 if vram_mb >= 4096 else torch.float32

        logger.info(f"Loading pipeline {model_id} ({repo_id}) dtype={dtype}")

        # cache_dir keeps all weights under data/models/diffusion (curated models
        # are downloaded on demand, HF-downloaded models are a cache hit).
        # No `revision` -> always loads the latest `main`.
        pipe = AutoPipelineForText2Image.from_pretrained(
            repo_id,
            torch_dtype=dtype,
            use_safetensors=True,
            cache_dir=str(settings.models_dir / "diffusion"),
            token=settings.huggingface_token or None,
        )

        if vram_mb >= 6144:
            try:
                pipe.enable_xformers_memory_efficient_attention()
                logger.info("xformers enabled")
            except Exception:
                logger.info("xformers not available, using SDPA")

        if vram_mb < 6144:
            pipe.enable_model_cpu_offload()
            logger.info("CPU offload enabled")
        elif vram_mb < 8192:
            pipe.enable_attention_slicing()
            pipe = pipe.to("cuda")
        else:
            pipe = pipe.to("cuda")

        return pipe

    def _get_vram_mb(self) -> int:
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.get_device_properties(0).total_memory // (1024 ** 2)
        except Exception:
            pass
        return 0

    async def unload_all(self) -> None:
        async with self._lock:
            self._loaded.clear()
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass


pipeline_manager = PipelineManager()


def image_to_base64(img: Image.Image, format: str = "JPEG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=format, quality=85)
    return base64.b64encode(buf.getvalue()).decode()
