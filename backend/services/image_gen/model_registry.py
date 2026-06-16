from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModelInfo:
    id: str
    name: str
    description: str
    pipeline_class: str
    repo_id: str
    min_vram_mb: int
    recommended_steps: int
    default_cfg: float
    supports_negative_prompt: bool = True
    default_width: int = 512
    default_height: int = 512
    tags: List[str] = field(default_factory=list)


MODEL_REGISTRY: List[ModelInfo] = [
    ModelInfo(
        id="sd15",
        name="Stable Diffusion 1.5",
        description="Classic SD model, great for artistic styles, low VRAM usage.",
        pipeline_class="StableDiffusionPipeline",
        repo_id="runwayml/stable-diffusion-v1-5",
        min_vram_mb=3000,
        recommended_steps=25,
        default_cfg=7.5,
        default_width=512,
        default_height=512,
        tags=["general", "artistic"],
    ),
    ModelInfo(
        id="sdxl",
        name="Stable Diffusion XL",
        description="High-resolution photorealistic generation. Requires ~7GB VRAM.",
        pipeline_class="StableDiffusionXLPipeline",
        repo_id="stabilityai/stable-diffusion-xl-base-1.0",
        min_vram_mb=6500,
        recommended_steps=30,
        default_cfg=7.5,
        default_width=1024,
        default_height=1024,
        tags=["photorealistic", "high-res"],
    ),
    ModelInfo(
        id="sdxl-turbo",
        name="SDXL Turbo",
        description="Real-time generation in 1-4 steps. CFG=0 recommended.",
        pipeline_class="StableDiffusionXLPipeline",
        repo_id="stabilityai/sdxl-turbo",
        min_vram_mb=5500,
        recommended_steps=4,
        default_cfg=0.0,
        supports_negative_prompt=False,
        default_width=512,
        default_height=512,
        tags=["fast", "turbo", "real-time"],
    ),
]

MODEL_REGISTRY_MAP = {m.id: m for m in MODEL_REGISTRY}


def get_model(model_id: str) -> Optional[ModelInfo]:
    return MODEL_REGISTRY_MAP.get(model_id)


def get_compatible_models(vram_mb: int) -> List[ModelInfo]:
    return [m for m in MODEL_REGISTRY if m.min_vram_mb <= vram_mb]
