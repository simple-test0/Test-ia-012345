"""Hardware-aware recommendation engine.

Turns a :class:`HardwareInfo` snapshot into concrete, backend-aware settings for
image generation, model training and local LLM agents.

Design goals
------------
* **Data-driven** — model line-ups and tier breakpoints live in plain tables
  (``IMAGE_TIERS`` / ``AGENT_TIERS``) so new hardware classes or models are a
  one-line edit, not a code change.
* **Backend-aware** — recommendations differ for NVIDIA CUDA, AMD ROCm, Intel
  XPU, Apple MPS and CPU (e.g. xformers is NVIDIA-only; ``torch.compile`` is
  skipped on MPS where it is still flaky).
* **Unified-memory aware** — Apple Silicon / CPU budgets are derived from system
  RAM instead of pretending there is dedicated VRAM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .detector import (
    BACKEND_CPU,
    BACKEND_CUDA,
    BACKEND_MPS,
    BACKEND_ROCM,
    BACKEND_XPU,
    HardwareInfo,
    detect_hardware,
)


@dataclass
class ImageGenRecommendations:
    recommended_models: List[str]
    max_resolution: tuple
    recommended_steps: int
    cfg_scale: float
    enable_xformers: bool
    enable_attention_slicing: bool
    enable_cpu_offload: bool
    enable_sequential_offload: bool
    use_fp16: bool
    # Newer, backend-aware knobs.
    attention_backend: str = "sdpa"  # "xformers" | "sdpa"
    enable_torch_compile: bool = False
    enable_vae_slicing: bool = False
    compute_dtype: str = "float16"  # "float16" | "bfloat16" | "float32"
    notes: str = ""


@dataclass
class TrainingRecommendations:
    recommended_batch_size: int
    recommended_learning_rate: float
    num_dataloader_workers: int
    use_mixed_precision: str
    gradient_accumulation_steps: int
    gradient_clip_norm: float
    max_recommended_params: int
    recommended_architectures: List[str]
    enable_torch_compile: bool = False
    pin_memory: bool = False
    notes: str = ""


@dataclass
class AgentRecommendations:
    recommended_models: List[str]
    context_window_tokens: int
    quantization: str
    notes: str = ""


@dataclass
class RecommendationSet:
    vram_mb: int
    ram_mb: int
    cpu_cores: int
    image_gen: ImageGenRecommendations
    training: TrainingRecommendations
    agent: AgentRecommendations
    tier_label: str
    backend: str = BACKEND_CPU
    total_vram_mb: int = 0
    gpu_count: int = 0


# ── Tier tables (edit these to add hardware classes / models) ────────────────
# Each entry: minimum usable memory (MB) to qualify for the tier. Ordered low→high.
# The *last* tier whose ``min_mb`` is satisfied wins.

IMAGE_TIERS = [
    {
        "min_mb": 0,
        "label": "CPU / Low memory",
        "models": ["sd15"],
        "max_resolution": (512, 512),
        "steps": 20,
        "cfg": 7.0,
        "attention_slicing": True,
        "vae_slicing": True,
        "cpu_offload": True,
        "sequential_offload": True,
        "fp16": False,
        "note": "CPU / sequential-offload mode — functional but slow. Prefer SDXL-Turbo/LCM for fewer steps.",
    },
    {
        "min_mb": 4096,
        "label": "Entry (4-6 GB)",
        "models": ["sdxl-turbo", "sd15"],
        "max_resolution": (768, 768),
        "steps": 6,
        "cfg": 1.0,
        "attention_slicing": True,
        "vae_slicing": True,
        "cpu_offload": True,
        "sequential_offload": False,
        "fp16": True,
        "note": "SDXL-Turbo (few-step) recommended; full SDXL may OOM. Keep ≤768px.",
    },
    {
        "min_mb": 6144,
        "label": "Mid (6-8 GB)",
        "models": ["sdxl-turbo", "sd15"],
        "max_resolution": (1024, 1024),
        "steps": 4,
        "cfg": 0.0,
        "attention_slicing": True,
        "vae_slicing": True,
        "cpu_offload": False,
        "sequential_offload": False,
        "fp16": True,
        "note": "SDXL-Turbo at 1024px (4 steps, CFG=0). Full SDXL with offload also possible.",
    },
    {
        "min_mb": 8192,
        "label": "High (8-12 GB)",
        "models": ["sdxl", "sdxl-turbo", "sd15"],
        "max_resolution": (1024, 1024),
        "steps": 30,
        "cfg": 7.5,
        "attention_slicing": False,
        "vae_slicing": False,
        "cpu_offload": False,
        "sequential_offload": False,
        "fp16": True,
        "note": "Full SDXL fits comfortably. SDPA + optional torch.compile for peak throughput.",
    },
    {
        "min_mb": 12288,
        "label": "High-End (12-16 GB)",
        "models": ["sdxl", "flux-schnell", "sdxl-turbo", "sd15"],
        "max_resolution": (1536, 1536),
        "steps": 30,
        "cfg": 7.5,
        "attention_slicing": False,
        "vae_slicing": False,
        "cpu_offload": False,
        "sequential_offload": False,
        "fp16": True,
        "note": "SDXL at high res; FLUX.1-schnell feasible with offload/quantization.",
    },
    {
        "min_mb": 16384,
        "label": "Enthusiast (16-24 GB)",
        "models": ["flux-schnell", "sd35-large", "sdxl", "sdxl-turbo"],
        "max_resolution": (2048, 2048),
        "steps": 35,
        "cfg": 7.5,
        "attention_slicing": False,
        "vae_slicing": False,
        "cpu_offload": False,
        "sequential_offload": False,
        "fp16": True,
        "note": "FLUX.1 / SD3.5 feasible. Multiple pipelines can be co-resident.",
    },
    {
        "min_mb": 24576,
        "label": "Workstation (24 GB+)",
        "models": ["flux-dev", "sd35-large", "flux-schnell", "sdxl"],
        "max_resolution": (2048, 2048),
        "steps": 40,
        "cfg": 7.5,
        "attention_slicing": False,
        "vae_slicing": False,
        "cpu_offload": False,
        "sequential_offload": False,
        "fp16": True,
        "note": "FLUX.1-dev / SD3.5-Large at full quality. ControlNet & img2img headroom.",
    },
]

AGENT_TIERS = [
    {
        "min_mb": 0,
        "models": ["llama3.2:1b", "qwen2.5:0.5b", "gemma2:2b"],
        "context": 4096,
        "quant": "q4_K_M",
        "note": "Tiny models only. CPU-only Ollama works for 1-3B models.",
    },
    {
        "min_mb": 4096,
        "models": ["llama3.2:3b", "phi4-mini", "qwen2.5:3b", "gemma2:2b"],
        "context": 8192,
        "quant": "q4_K_M",
        "note": "3-4B models at 4-bit are responsive on entry GPUs.",
    },
    {
        "min_mb": 8192,
        "models": ["llama3.1:8b", "qwen2.5:7b", "qwen2.5-coder:7b", "deepseek-r1:7b"],
        "context": 16384,
        "quant": "q4_K_M",
        "note": "7-8B models at 4-bit fit comfortably with a roomy context window.",
    },
    {
        "min_mb": 12288,
        "models": ["qwen2.5:14b", "qwen2.5-coder:14b", "phi4", "llama3.1:8b"],
        "context": 32768,
        "quant": "q4_K_M",
        "note": "14B at 4-bit, or 7-8B at q8_0 for higher fidelity.",
    },
    {
        "min_mb": 24576,
        "models": ["qwen2.5:32b", "qwen2.5-coder:32b", "deepseek-r1:32b", "gemma2:27b"],
        "context": 32768,
        "quant": "q4_K_M",
        "note": "32B-class models at 4-bit (≈22 GB). Best single-GPU quality tier.",
    },
    {
        "min_mb": 49152,
        "models": ["llama3.3:70b", "qwen2.5:72b", "deepseek-r1:70b"],
        "context": 65536,
        "quant": "q4_K_M",
        "note": "70B flagships. 48 GB+ (or multi-GPU) recommended.",
    },
]


def _pick_tier(tiers: list, budget_mb: int) -> dict:
    chosen = tiers[0]
    for tier in tiers:
        if budget_mb >= tier["min_mb"]:
            chosen = tier
        else:
            break
    return chosen


def _tier_budget(budget_mb: int) -> int:
    """Memory budget used for *tier selection only* (never for sizing math).

    Discrete GPUs report slightly less than their nominal VRAM because the
    driver reserves some (an "8 GB" RTX 4060 Ti exposes ~8188 MB, a "12 GB" card
    ~12282 MB). With exact-nominal breakpoints every card would land one tier too
    low. A ~4% headroom snaps these back to the intended tier without affecting
    batch-size / max-param calculations (which keep the true, conservative value).
    It is tight enough not to over-promote a genuine lower tier (a true 6 GB card
    stays in the 6 GB tier).
    """
    return int(budget_mb * 1.04)


def _get_tier_label(budget_mb: int) -> str:
    return _pick_tier(IMAGE_TIERS, budget_mb)["label"]


# Rough bytes-per-element for activations/grads at the recommended precision.
# fp16/bf16 mixed precision roughly halves activation memory vs fp32.
def _compute_batch_size(budget_mb: int, fp16: bool) -> int:
    usable = int(budget_mb * 0.8)
    per_sample = 256 if fp16 else 512
    return max(1, usable // per_sample)


def _compute_max_params(budget_mb: int, fp16: bool) -> int:
    usable_bytes = int(budget_mb * 1024 * 1024 * 0.7)
    # Mixed precision training keeps fp32 master weights + optimizer state; budget
    # ~12 bytes/param for Adam-class optimizers (4 weight + 8 moments) and a bit
    # more headroom for activations.
    bytes_per_param = 12 if fp16 else 16
    return usable_bytes // bytes_per_param


def _compute_grad_accum(batch: int, target_effective_batch: int = 32) -> int:
    return max(1, target_effective_batch // max(1, batch))


def recommend(hw: Optional[HardwareInfo] = None) -> RecommendationSet:
    if hw is None:
        hw = detect_hardware()

    gpu = hw.primary_gpu
    backend = hw.accelerator_backend
    # Usable memory budget: dedicated VRAM for discrete accelerators, otherwise a
    # safe slice of system RAM (unified memory / CPU).
    if gpu and not gpu.is_unified_memory:
        budget_mb = gpu.vram_total_mb
    elif gpu and gpu.is_unified_memory:
        budget_mb = gpu.vram_total_mb  # already RAM-derived in the detector
    else:
        budget_mb = int(hw.ram_total_mb * 0.7)

    # Headroom-adjusted budget for tier selection (model line-up, capability
    # flags). Sizing math below keeps the true ``budget_mb``.
    tier_budget = _tier_budget(budget_mb)

    ram_mb = hw.ram_total_mb
    cpu_cores = hw.cpu.logical_cores if hw.cpu else 4

    # Backend capability flags.
    is_nvidia = backend == BACKEND_CUDA
    is_discrete = backend in (BACKEND_CUDA, BACKEND_ROCM, BACKEND_XPU)
    supports_amp = backend in (BACKEND_CUDA, BACKEND_ROCM, BACKEND_XPU)
    # torch.compile is solid on CUDA/XPU; still unreliable on MPS, pointless on CPU.
    supports_compile = backend in (BACKEND_CUDA, BACKEND_ROCM, BACKEND_XPU)
    # bf16 is the safe mixed-precision dtype on Apple/Ampere+; fp16 on older CUDA.
    prefer_bf16 = backend in (BACKEND_MPS, BACKEND_XPU)

    image_gen = _recommend_image(tier_budget, backend, is_nvidia, supports_compile, prefer_bf16)
    training = _recommend_training(budget_mb, tier_budget, cpu_cores, supports_amp, supports_compile,
                                   is_discrete, prefer_bf16)
    agent = _recommend_agent(tier_budget, backend)

    return RecommendationSet(
        vram_mb=budget_mb if is_discrete else 0,
        ram_mb=ram_mb,
        cpu_cores=cpu_cores,
        image_gen=image_gen,
        training=training,
        agent=agent,
        tier_label=f"{_get_tier_label(tier_budget)} · {backend.upper()}",
        backend=backend,
        total_vram_mb=hw.total_vram_mb,
        gpu_count=len([g for g in hw.gpus if not g.is_unified_memory]),
    )


def _recommend_image(budget_mb, backend, is_nvidia, supports_compile, prefer_bf16):
    tier = _pick_tier(IMAGE_TIERS, budget_mb)
    fp16 = tier["fp16"] and backend != BACKEND_CPU
    # MPS/XPU prefer bf16; CPU stays fp32; NVIDIA uses fp16.
    if not fp16:
        compute_dtype = "float32"
    elif prefer_bf16:
        compute_dtype = "bfloat16"
    else:
        compute_dtype = "float16"

    attention_backend = "xformers" if (is_nvidia and budget_mb >= 6144) else "sdpa"
    notes = tier["note"]
    if backend == BACKEND_MPS:
        notes += " Apple MPS: SDPA attention, bf16, no CPU offload needed (unified memory)."
    elif backend == BACKEND_ROCM:
        notes += " AMD ROCm: SDPA attention (xformers unsupported)."
    elif backend == BACKEND_XPU:
        notes += " Intel XPU: SDPA attention, bf16 recommended."

    return ImageGenRecommendations(
        recommended_models=tier["models"],
        max_resolution=tier["max_resolution"],
        recommended_steps=tier["steps"],
        cfg_scale=tier["cfg"],
        enable_xformers=attention_backend == "xformers",
        enable_attention_slicing=tier["attention_slicing"],
        enable_cpu_offload=tier["cpu_offload"] and backend != BACKEND_MPS,
        enable_sequential_offload=tier["sequential_offload"] and backend != BACKEND_MPS,
        use_fp16=fp16,
        attention_backend=attention_backend,
        enable_torch_compile=supports_compile and budget_mb >= 8192,
        enable_vae_slicing=tier["vae_slicing"],
        compute_dtype=compute_dtype,
        notes=notes,
    )


def _recommend_training(budget_mb, tier_budget, cpu_cores, supports_amp, supports_compile,
                        is_discrete, prefer_bf16):
    use_amp = supports_amp and tier_budget >= 4096
    fp16_sizing = use_amp
    # Sizing uses the *true* (conservative) budget so we never over-commit VRAM.
    batch = _compute_batch_size(budget_mb, fp16_sizing)
    max_params = _compute_max_params(budget_mb, fp16_sizing)
    grad_accum = _compute_grad_accum(batch)
    num_workers = min(max(cpu_cores // 2, 1), 8)

    if not use_amp:
        precision = "no"
    elif prefer_bf16:
        precision = "bf16"
    else:
        precision = "fp16"

    feasible_archs = ["cnn", "rnn", "lstm", "gru"]
    if tier_budget >= 2048:
        feasible_archs += ["pretrained", "transformer"]
    if tier_budget >= 3072:
        feasible_archs.append("vit")

    return TrainingRecommendations(
        recommended_batch_size=batch,
        recommended_learning_rate=3e-4,
        num_dataloader_workers=num_workers,
        use_mixed_precision=precision,
        gradient_accumulation_steps=grad_accum,
        gradient_clip_norm=1.0,
        max_recommended_params=max_params,
        recommended_architectures=feasible_archs,
        enable_torch_compile=supports_compile and tier_budget >= 6144,
        pin_memory=is_discrete,
        notes=(
            f"Effective batch size: {batch * grad_accum} "
            f"({batch} per step x {grad_accum} grad-accum). "
            f"Max model size ≈ {max_params // 1_000_000}M params at {precision or 'fp32'} precision."
        ),
    )


def _recommend_agent(budget_mb, backend):
    tier = _pick_tier(AGENT_TIERS, budget_mb)
    note = tier["note"]
    if backend == BACKEND_CPU:
        note += " No GPU detected — expect lower tokens/sec; keep models ≤3B for interactivity."
    elif backend == BACKEND_MPS:
        note += " Ollama uses Metal acceleration on Apple Silicon."
    return AgentRecommendations(
        recommended_models=tier["models"],
        context_window_tokens=tier["context"],
        quantization=tier["quant"],
        notes=note,
    )
