"""Registry of available text-to-image models.

The registry is intentionally data-driven: new checkpoints are added by
appending a :class:`ModelInfo` (or calling :func:`register_model` at runtime),
without touching the pipeline/worker code. ``AutoPipelineForText2Image`` resolves
the concrete pipeline class from ``repo_id`` automatically, so adding a model is
usually a one-line change.
"""

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
    # ``gated`` models require accepting a license on the Hugging Face Hub and a
    # configured ``HUGGINGFACE_TOKEN``. Surfaced to the UI so users aren't met
    # with an opaque 401 at generation time.
    gated: bool = False
    family: str = ""


MODEL_REGISTRY: List[ModelInfo] = [
    ModelInfo(
        id="sd15",
        name="Stable Diffusion 1.5",
        description="Classic SD model, great for artistic styles, low VRAM usage.",
        pipeline_class="StableDiffusionPipeline",
        repo_id="stable-diffusion-v1-5/stable-diffusion-v1-5",
        min_vram_mb=0,
        recommended_steps=25,
        default_cfg=7.5,
        default_width=512,
        default_height=512,
        tags=["general", "artistic", "low-vram"],
        family="sd",
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
        family="sdxl",
    ),
    ModelInfo(
        id="sdxl-turbo",
        name="SDXL Turbo",
        description="Real-time generation in 1-4 steps. CFG=0 recommended.",
        pipeline_class="StableDiffusionXLPipeline",
        repo_id="stabilityai/sdxl-turbo",
        min_vram_mb=4096,
        recommended_steps=4,
        default_cfg=0.0,
        supports_negative_prompt=False,
        default_width=512,
        default_height=512,
        tags=["fast", "turbo", "real-time", "few-step"],
        family="sdxl",
    ),
    ModelInfo(
        id="flux-schnell",
        name="FLUX.1 [schnell]",
        description="Fast 4-step rectified-flow transformer model. Apache-2.0, no CFG.",
        pipeline_class="FluxPipeline",
        repo_id="black-forest-labs/FLUX.1-schnell",
        min_vram_mb=12000,
        recommended_steps=4,
        default_cfg=0.0,
        supports_negative_prompt=False,
        default_width=1024,
        default_height=1024,
        tags=["fast", "few-step", "flux", "high-quality"],
        family="flux",
    ),
    ModelInfo(
        id="flux-dev",
        name="FLUX.1 [dev]",
        description="High-fidelity 12B rectified-flow transformer. Gated (non-commercial license).",
        pipeline_class="FluxPipeline",
        repo_id="black-forest-labs/FLUX.1-dev",
        min_vram_mb=24000,
        recommended_steps=28,
        default_cfg=3.5,
        default_width=1024,
        default_height=1024,
        tags=["flux", "high-quality", "gated"],
        gated=True,
        family="flux",
    ),
    ModelInfo(
        id="sd35-large",
        name="Stable Diffusion 3.5 Large",
        description="8B MMDiT model with strong prompt adherence and typography. Gated.",
        pipeline_class="StableDiffusion3Pipeline",
        repo_id="stabilityai/stable-diffusion-3.5-large",
        min_vram_mb=16000,
        recommended_steps=28,
        default_cfg=4.5,
        default_width=1024,
        default_height=1024,
        tags=["sd3", "high-quality", "typography", "gated"],
        gated=True,
        family="sd3",
    ),
]

MODEL_REGISTRY_MAP = {m.id: m for m in MODEL_REGISTRY}


def register_model(model: ModelInfo, *, overwrite: bool = False) -> None:
    """Add (or replace) a model at runtime. Enables plugins / user config."""
    if model.id in MODEL_REGISTRY_MAP and not overwrite:
        raise ValueError(f"Model '{model.id}' already registered")
    MODEL_REGISTRY_MAP[model.id] = model
    MODEL_REGISTRY[:] = [m for m in MODEL_REGISTRY if m.id != model.id] + [model]


def get_model(model_id: str) -> Optional[ModelInfo]:
    return MODEL_REGISTRY_MAP.get(model_id)


def get_compatible_models(vram_mb: int) -> List[ModelInfo]:
    """Models whose minimum memory footprint fits the given budget.

    A budget of 0 (CPU-only / undetected) still returns models that can run with
    offloading, so the UI is never empty.
    """
    if vram_mb <= 0:
        return [m for m in MODEL_REGISTRY if m.min_vram_mb <= 4096]
    return [m for m in MODEL_REGISTRY if m.min_vram_mb <= vram_mb]
