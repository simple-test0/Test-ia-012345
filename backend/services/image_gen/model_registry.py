from dataclasses import dataclass, field
from typing import NamedTuple


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
    tags: list[str] = field(default_factory=list)
    # Gated models require accepting a license on HF + a HUGGINGFACE_TOKEN.
    gated: bool = False


MODEL_REGISTRY: list[ModelInfo] = [
    ModelInfo(
        id="sd15",
        name="Stable Diffusion 1.5",
        description="Classic SD model, great for artistic styles, low VRAM usage.",
        pipeline_class="StableDiffusionPipeline",
        # runwayml/stable-diffusion-v1-5 was removed from HF (Aug 2024);
        # use the community-maintained mirror.
        repo_id="stable-diffusion-v1-5/stable-diffusion-v1-5",
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
    ModelInfo(
        id="flux-schnell",
        name="FLUX.1 schnell",
        description="State-of-the-art open model (Apache-2.0). 1-4 steps, CFG=0. Large (~24GB).",
        pipeline_class="FluxPipeline",
        repo_id="black-forest-labs/FLUX.1-schnell",
        min_vram_mb=22000,
        recommended_steps=4,
        default_cfg=0.0,
        supports_negative_prompt=False,
        default_width=1024,
        default_height=1024,
        tags=["flux", "fast", "high-res", "sota"],
    ),
    ModelInfo(
        id="flux-dev",
        name="FLUX.1 dev (gated)",
        description="Top-quality FLUX model. Gated: needs a HF token + license acceptance.",
        pipeline_class="FluxPipeline",
        repo_id="black-forest-labs/FLUX.1-dev",
        min_vram_mb=24000,
        recommended_steps=28,
        default_cfg=3.5,
        supports_negative_prompt=False,
        default_width=1024,
        default_height=1024,
        tags=["flux", "high-res", "sota"],
        gated=True,
    ),
    ModelInfo(
        id="sd35",
        name="Stable Diffusion 3.5 Large (gated)",
        description="Latest SD family, excellent prompt/typography. Gated: needs HF token + license.",
        pipeline_class="StableDiffusion3Pipeline",
        repo_id="stabilityai/stable-diffusion-3.5-large",
        min_vram_mb=18000,
        recommended_steps=28,
        default_cfg=4.5,
        default_width=1024,
        default_height=1024,
        tags=["stable-diffusion", "high-res", "sota"],
        gated=True,
    ),
]

MODEL_REGISTRY_MAP = {m.id: m for m in MODEL_REGISTRY}
CURATED_IDS = set(MODEL_REGISTRY_MAP)


def get_model(model_id: str) -> ModelInfo | None:
    return MODEL_REGISTRY_MAP.get(model_id)


def get_compatible_models(vram_mb: int) -> list[ModelInfo]:
    return [m for m in MODEL_REGISTRY if m.min_vram_mb <= vram_mb]


def curated_models() -> list[ModelInfo]:
    """Recommended models, in curated (recommended-first) order."""
    return list(MODEL_REGISTRY)


class ResolvedModel(NamedTuple):
    model_id: str
    repo_id: str
    source: str  # "curated" | "downloaded"
    min_vram_mb: int
    recommended_steps: int
    default_cfg: float
    default_width: int
    default_height: int
    supports_negative_prompt: bool


async def resolve_model(model_id: str, db) -> ResolvedModel | None:
    """Resolve a model_id to its repo_id + metadata.

    Looks up curated models first, then the DiffusionModel table for
    user-downloaded models (only those with status == "ready").
    Returns None if not found or not ready.
    """
    curated = MODEL_REGISTRY_MAP.get(model_id)
    if curated is not None:
        return ResolvedModel(
            model_id=curated.id,
            repo_id=curated.repo_id,
            source="curated",
            min_vram_mb=curated.min_vram_mb,
            recommended_steps=curated.recommended_steps,
            default_cfg=curated.default_cfg,
            default_width=curated.default_width,
            default_height=curated.default_height,
            supports_negative_prompt=curated.supports_negative_prompt,
        )

    # Downloaded model — look it up in the database.
    from sqlalchemy import select

    from models.diffusion_model import DiffusionModel

    result = await db.execute(
        select(DiffusionModel).where(DiffusionModel.id == model_id)
    )
    rec = result.scalar_one_or_none()
    if rec is None or rec.status != "ready":
        return None

    return ResolvedModel(
        model_id=rec.id,
        repo_id=rec.repo_id,
        source="downloaded",
        min_vram_mb=rec.min_vram_mb or 0,
        recommended_steps=rec.recommended_steps or 25,
        default_cfg=rec.default_cfg or 7.5,
        default_width=rec.default_width or 512,
        default_height=rec.default_height or 512,
        supports_negative_prompt=rec.supports_negative_prompt,
    )
