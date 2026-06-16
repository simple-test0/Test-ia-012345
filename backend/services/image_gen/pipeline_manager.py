"""Diffusion pipeline cache + loader.

Backend-agnostic: picks the right torch device (CUDA / ROCm / XPU / MPS / CPU),
the right dtype, and the right memory-saving strategy based on the detected
hardware and the recommender. Loaded pipelines are cached LRU-style up to
``settings.max_pipelines_loaded`` so repeated generations reuse the warm model
instead of re-loading from disk.
"""
import asyncio
import base64
import io
import logging
from collections import OrderedDict
from typing import Optional

from PIL import Image

from core.config import settings
from hardware.detector import (
    BACKEND_CPU,
    BACKEND_CUDA,
    BACKEND_MPS,
    detect_hardware,
    empty_accelerator_cache,
)
from hardware.recommender import recommend

logger = logging.getLogger(__name__)


class PipelineManager:
    def __init__(self, max_loaded: Optional[int] = None):
        self._max_loaded = max_loaded or max(1, settings.max_pipelines_loaded)
        self._loaded: "OrderedDict[str, object]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_pipeline(self, model_id: str, repo_id: str):
        async with self._lock:
            if model_id in self._loaded:
                self._loaded.move_to_end(model_id)
                return self._loaded[model_id]

            while len(self._loaded) >= self._max_loaded:
                oldest_id, oldest_pipe = self._loaded.popitem(last=False)
                logger.info("Evicting pipeline: %s", oldest_id)
                del oldest_pipe
                empty_accelerator_cache()

            pipe = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._load_pipeline(model_id, repo_id)
            )
            self._loaded[model_id] = pipe
            return pipe

    def _load_pipeline(self, model_id: str, repo_id: str):
        import torch
        from diffusers import AutoPipelineForText2Image

        hw = detect_hardware()
        rec = recommend(hw).image_gen
        device = self._resolve_device(hw)
        dtype = self._resolve_dtype(torch, rec.compute_dtype, device)

        logger.info("Loading pipeline %s (%s) device=%s dtype=%s", model_id, repo_id, device, dtype)

        token = settings.huggingface_token or None
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo_id,
                torch_dtype=dtype,
                use_safetensors=True,
                token=token,
            )
        except Exception:
            # Some repos only ship non-safetensors weights; retry once.
            logger.warning("safetensors load failed for %s, retrying without", repo_id, exc_info=True)
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo_id, torch_dtype=dtype, token=token
            )

        self._apply_optimizations(pipe, rec, device, torch)
        return pipe

    def _apply_optimizations(self, pipe, rec, device: str, torch) -> None:
        # Attention backend: xformers only helps on NVIDIA; everywhere else the
        # native PyTorch SDPA kernels are as fast and far more portable.
        if rec.enable_xformers:
            try:
                pipe.enable_xformers_memory_efficient_attention()
                logger.info("xformers attention enabled")
            except Exception:
                logger.info("xformers unavailable, falling back to SDPA", exc_info=False)

        if rec.enable_vae_slicing:
            try:
                pipe.enable_vae_slicing()
            except Exception:
                logger.debug("vae slicing unsupported", exc_info=True)
        if rec.enable_attention_slicing:
            try:
                pipe.enable_attention_slicing()
            except Exception:
                logger.debug("attention slicing unsupported", exc_info=True)

        # Memory placement strategy.
        if rec.enable_sequential_offload:
            try:
                pipe.enable_sequential_cpu_offload()
                logger.info("sequential CPU offload enabled")
                return  # offload manages device placement itself
            except Exception:
                logger.debug("sequential offload unsupported", exc_info=True)
        if rec.enable_cpu_offload:
            try:
                pipe.enable_model_cpu_offload()
                logger.info("model CPU offload enabled")
                return
            except Exception:
                logger.debug("model offload unsupported", exc_info=True)

        try:
            pipe = pipe.to(device)
        except Exception:
            logger.warning("Could not move pipeline to %s; staying on CPU", device, exc_info=True)
            return

        if rec.enable_torch_compile and settings.enable_torch_compile:
            # UNet for SD/SDXL, transformer (DiT) for SD3/FLUX.
            target = "transformer" if hasattr(pipe, "transformer") else "unet"
            try:
                module = getattr(pipe, target, None)
                if module is not None:
                    setattr(pipe, target, torch.compile(module, mode="reduce-overhead", fullgraph=False))
                    logger.info("torch.compile applied to %s", target)
            except Exception:
                logger.debug("torch.compile failed", exc_info=True)

    @staticmethod
    def _resolve_device(hw) -> str:
        if settings.device_preference:
            return settings.device_preference
        gpu = hw.primary_gpu
        return gpu.device_str if gpu else "cpu"

    @staticmethod
    def _resolve_dtype(torch, compute_dtype: str, device: str):
        if device.startswith("cpu"):
            return torch.float32
        if compute_dtype == "bfloat16":
            return torch.bfloat16
        if compute_dtype == "float32":
            return torch.float32
        return torch.float16

    async def unload_all(self) -> None:
        async with self._lock:
            self._loaded.clear()
            empty_accelerator_cache()


pipeline_manager = PipelineManager()


def image_to_base64(img: Image.Image, format: str = "JPEG") -> str:
    buf = io.BytesIO()
    if format.upper() in ("JPEG", "JPG") and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.save(buf, format=format, quality=85)
    return base64.b64encode(buf.getvalue()).decode()
