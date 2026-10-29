import asyncio
import base64
import gc
import io
import logging
from collections import OrderedDict

from PIL import Image

from core.config import settings

logger = logging.getLogger(__name__)


# Map UI sampler names to diffusers scheduler classes (+ optional config kwargs).
_SAMPLER_MAP = {
    "DPM++ 2M": ("DPMSolverMultistepScheduler", {"algorithm_type": "dpmsolver++"}),
    "DPM++ 2M Karras": (
        "DPMSolverMultistepScheduler",
        {"algorithm_type": "dpmsolver++", "use_karras_sigmas": True},
    ),
    "Euler": ("EulerDiscreteScheduler", {}),
    "Euler a": ("EulerAncestralDiscreteScheduler", {}),
    "DDIM": ("DDIMScheduler", {}),
    "LMS": ("LMSDiscreteScheduler", {}),
}

SAMPLERS = list(_SAMPLER_MAP)


def apply_sampler(pipe, sampler: str) -> None:
    """Swap the pipeline scheduler to match the requested sampler.

    Best-effort: some pipelines (e.g. FLUX, SD3) use flow-matching schedulers
    that are incompatible with these samplers, so they are left untouched.
    """
    entry = _SAMPLER_MAP.get(sampler)
    if not entry or not hasattr(pipe, "scheduler"):
        return
    current = type(pipe.scheduler).__name__
    if "FlowMatch" in current:
        return
    cls_name, extra = entry
    try:
        import diffusers

        scheduler_cls = getattr(diffusers, cls_name, None)
        if scheduler_cls is None:
            return
        # Keep the original config so switching back and forth is lossless.
        if not hasattr(pipe, "_original_scheduler_config"):
            pipe._original_scheduler_config = pipe.scheduler.config
        pipe.scheduler = scheduler_cls.from_config(pipe._original_scheduler_config, **extra)
        logger.info(f"Applied sampler {sampler} -> {cls_name}")
    except Exception as exc:
        logger.info(f"Could not apply sampler {sampler}: {exc}")


def select_device() -> str:
    """Best available torch device: cuda > mps (Apple Silicon) > cpu."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


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

            while self._loaded and len(self._loaded) >= self._max_loaded:
                oldest_id, oldest_pipe = self._loaded.popitem(last=False)
                logger.info(f"Evicting pipeline: {oldest_id}")
                del oldest_pipe
                _free_memory()

            pipe = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._load_pipeline(model_id, repo_id)
            )
            self._loaded[model_id] = pipe
            return pipe

    def _load_pipeline(self, model_id: str, repo_id: str):
        import torch
        from diffusers import AutoPipelineForText2Image

        device = select_device()
        vram_mb = self._get_vram_mb() if device == "cuda" else 0

        if device == "cuda":
            if "flux" in repo_id.lower() and torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16  # FLUX is trained in bf16; fp16 can give black images
            else:
                dtype = torch.float16 if vram_mb >= 4096 else torch.float32
        elif device == "mps":
            dtype = torch.float16
        else:
            dtype = torch.float32  # half precision is very slow / unsupported on CPU

        logger.info(f"Loading pipeline {model_id} ({repo_id}) on {device} dtype={dtype}")

        # cache_dir keeps all weights under data/models/diffusion (curated models
        # are downloaded on demand, HF-downloaded models are a cache hit).
        # No `revision` -> always loads the latest `main`.
        common = dict(
            torch_dtype=dtype,
            cache_dir=str(settings.models_dir / "diffusion"),
            token=settings.huggingface_token or None,
        )
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo_id, use_safetensors=True, **common
            )
        except (OSError, EnvironmentError, ValueError) as exc:
            # Some community repos only ship .bin weights.
            logger.info(f"No safetensors for {repo_id} ({exc}); retrying with any format")
            pipe = AutoPipelineForText2Image.from_pretrained(repo_id, **common)

        if device == "cuda":
            if vram_mb >= 6144:
                try:
                    pipe.enable_xformers_memory_efficient_attention()
                    logger.info("xformers enabled")
                except Exception:
                    logger.info("xformers not available, using PyTorch SDPA")

            if vram_mb < 6144:
                pipe.enable_model_cpu_offload()
                logger.info("CPU offload enabled")
            elif vram_mb < 8192:
                pipe.enable_attention_slicing()
                pipe = pipe.to("cuda")
            else:
                pipe = pipe.to("cuda")
            if vram_mb < 8192 and hasattr(pipe, "enable_vae_tiling"):
                pipe.enable_vae_tiling()  # avoids OOM when decoding large images
        elif device == "mps":
            pipe = pipe.to("mps")
            pipe.enable_attention_slicing()  # recommended for Macs with < 64 GB
        # CPU: keep PyTorch's fused SDPA attention. Attention slicing would
        # force the slow reference implementation (several times slower).

        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:
            pass
        pipe._aistudio_device = device
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
            _free_memory()


def _free_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


pipeline_manager = PipelineManager(max_loaded=max(1, settings.max_pipelines_loaded))


def image_to_base64(img: Image.Image, format: str = "JPEG", quality: int = 85) -> str:
    buf = io.BytesIO()
    if format.upper() == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format=format, quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def image_to_data_url(img: Image.Image, format: str = "JPEG") -> str:
    """Return a ready-to-render `data:` URL (used for live step previews)."""
    mime = "jpeg" if format.upper() == "JPEG" else format.lower()
    return f"data:image/{mime};base64,{image_to_base64(img, format)}"
