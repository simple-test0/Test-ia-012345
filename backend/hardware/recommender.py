from dataclasses import dataclass, field
from typing import List, Optional

from .detector import HardwareInfo, detect_hardware


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


def _compute_batch_size(vram_mb: int) -> int:
    usable = int(vram_mb * 0.8)
    return max(1, usable // 512)


def _compute_max_params(vram_mb: int) -> int:
    usable_bytes = int(vram_mb * 1024 * 1024 * 0.7)
    return usable_bytes // 10


def _compute_grad_accum(vram_mb: int, target_effective_batch: int = 32) -> int:
    batch = _compute_batch_size(vram_mb)
    return max(1, target_effective_batch // batch)


def _get_tier_label(vram_mb: int) -> str:
    if vram_mb < 4096:
        return "CPU / Low VRAM (< 4 GB)"
    elif vram_mb < 6144:
        return "Entry GPU (4-6 GB)"
    elif vram_mb < 8192:
        return "Mid GPU (6-8 GB)"
    elif vram_mb < 12288:
        return "High GPU (8-12 GB)"
    elif vram_mb < 16384:
        return "High-End GPU (12-16 GB)"
    elif vram_mb < 24576:
        return "Enthusiast GPU (16-24 GB)"
    else:
        return "Workstation / Multi-GPU (> 24 GB)"


def recommend(hw: Optional[HardwareInfo] = None) -> RecommendationSet:
    if hw is None:
        hw = detect_hardware()

    vram_mb = hw.gpus[0].vram_total_mb if hw.gpus else 0
    ram_mb = hw.ram_total_mb
    cpu_cores = hw.cpu.logical_cores if hw.cpu else 4

    # ── Image Generation ──────────────────────────────────────────────────────
    if vram_mb < 4096:
        img = ImageGenRecommendations(
            recommended_models=["sd15"],
            max_resolution=(512, 512),
            recommended_steps=20,
            cfg_scale=7.0,
            enable_xformers=False,
            enable_attention_slicing=True,
            enable_cpu_offload=True,
            enable_sequential_offload=True,
            use_fp16=False,
            notes="CPU offload mode — slow but functional without a GPU.",
        )
    elif vram_mb < 6144:
        img = ImageGenRecommendations(
            recommended_models=["sd15"],
            max_resolution=(768, 768),
            recommended_steps=25,
            cfg_scale=7.0,
            enable_xformers=True,
            enable_attention_slicing=True,
            enable_cpu_offload=True,
            enable_sequential_offload=False,
            use_fp16=True,
            notes="SD 1.5 only; SDXL will OOM. Keep resolution ≤ 768px.",
        )
    elif vram_mb < 8192:
        img = ImageGenRecommendations(
            recommended_models=[
                "sdxl-turbo",
                "sd15",
            ],
            max_resolution=(1024, 1024),
            recommended_steps=4,
            cfg_scale=0.0,
            enable_xformers=True,
            enable_attention_slicing=True,
            enable_cpu_offload=False,
            enable_sequential_offload=False,
            use_fp16=True,
            notes="SDXL-Turbo recommended (4 steps, CFG=0). SDXL full may need attention slicing.",
        )
    elif vram_mb < 12288:
        img = ImageGenRecommendations(
            recommended_models=[
                "sdxl",
                "sdxl-turbo",
                "sd15",
            ],
            max_resolution=(1024, 1024),
            recommended_steps=30,
            cfg_scale=7.5,
            enable_xformers=True,
            enable_attention_slicing=False,
            enable_cpu_offload=False,
            enable_sequential_offload=False,
            use_fp16=True,
            notes="Full SDXL fits comfortably. xformers enabled for peak throughput.",
        )
    else:
        img = ImageGenRecommendations(
            recommended_models=[
                "flux-schnell",
                "sdxl",
                "sdxl-turbo",
                "sd15",
            ],
            max_resolution=(2048, 2048),
            recommended_steps=35,
            cfg_scale=7.5,
            enable_xformers=True,
            enable_attention_slicing=False,
            enable_cpu_offload=False,
            enable_sequential_offload=False,
            use_fp16=True,
            notes="Multiple pipelines can be loaded. ControlNet or img2img also feasible.",
        )

    # ── Training ──────────────────────────────────────────────────────────────
    batch = _compute_batch_size(vram_mb)
    max_params = _compute_max_params(vram_mb)
    grad_accum = _compute_grad_accum(vram_mb)
    num_workers = min(cpu_cores // 2, 8)

    feasible_archs = []
    if vram_mb >= 1024:
        feasible_archs += ["cnn", "rnn", "lstm"]
    if vram_mb >= 2048:
        feasible_archs += ["transformer"]
    if vram_mb >= 3072:
        feasible_archs += ["vit"]

    training = TrainingRecommendations(
        recommended_batch_size=batch,
        recommended_learning_rate=3e-4,
        num_dataloader_workers=num_workers,
        use_mixed_precision="fp16" if vram_mb >= 4096 else "no",
        gradient_accumulation_steps=grad_accum,
        gradient_clip_norm=1.0,
        max_recommended_params=max_params,
        recommended_architectures=feasible_archs or ["cnn"],
        notes=(
            f"Effective batch size: {batch * grad_accum} "
            f"({batch} per step × {grad_accum} gradient accumulation steps). "
            f"Max model size ≈ {max_params // 1_000_000}M parameters."
        ),
    )

    # ── Agent / LLM ───────────────────────────────────────────────────────────
    if vram_mb < 4096:
        agent = AgentRecommendations(
            recommended_models=["phi3:mini", "gemma:2b"],
            context_window_tokens=2048,
            quantization="q4_K_M",
            notes="Small quantized models only. Consider CPU-only Ollama mode.",
        )
    elif vram_mb < 8192:
        agent = AgentRecommendations(
            recommended_models=["llama3:8b-instruct-q4_K_M", "mistral:7b-instruct-q4_K_M"],
            context_window_tokens=4096,
            quantization="q4_K_M",
            notes="7-8B models at 4-bit quantization fit comfortably.",
        )
    elif vram_mb < 12288:
        agent = AgentRecommendations(
            recommended_models=[
                "llama3:8b-instruct-q8_0",
                "mistral:7b-instruct-q8_0",
                "llama3:8b-instruct-q4_K_M",
            ],
            context_window_tokens=8192,
            quantization="q8_0",
            notes="7-8B models at 8-bit, or 13B at 4-bit. Better quality than 4-bit.",
        )
    else:
        agent = AgentRecommendations(
            recommended_models=[
                "llama3:70b-instruct-q4_K_M",
                "codellama:34b-instruct-q4_K_M",
                "mixtral:8x7b-instruct-q4_K_M",
            ],
            context_window_tokens=32768,
            quantization="q4_K_M",
            notes="Large models possible. 34B or 70B at 4-bit quantization.",
        )

    return RecommendationSet(
        vram_mb=vram_mb,
        ram_mb=ram_mb,
        cpu_cores=cpu_cores,
        image_gen=img,
        training=training,
        agent=agent,
        tier_label=_get_tier_label(vram_mb),
    )
