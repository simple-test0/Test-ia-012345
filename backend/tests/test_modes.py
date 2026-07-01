"""Unit tests for generation modes helpers (img2img / ControlNet)."""
import base64
import importlib.util
import io

import pytest

from services.image_gen.modes import (
    CONTROLNET_TYPES,
    MAX_INPUT_IMAGE_BYTES,
    SUPPORTED_MODES,
    controlnet_repo_for,
    decode_image_payload,
    detect_family,
)

_HAS_PIL = importlib.util.find_spec("PIL") is not None
needs_pil = pytest.mark.skipif(not _HAS_PIL, reason="Pillow not installed")


# ── Family detection ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pipeline_class,repo_id,expected", [
    ("StableDiffusionPipeline", "stable-diffusion-v1-5/stable-diffusion-v1-5", "sd15"),
    ("StableDiffusionXLPipeline", "stabilityai/stable-diffusion-xl-base-1.0", "sdxl"),
    ("StableDiffusionXLPipeline", "stabilityai/sdxl-turbo", "sdxl"),
    ("FluxPipeline", "black-forest-labs/FLUX.1-schnell", None),
    ("StableDiffusion3Pipeline", "stabilityai/stable-diffusion-3.5-large", None),
    # Downloaded models only carry an HF pipeline tag -> repo-id heuristics.
    ("text-to-image", "someuser/my-sdxl-finetune", "sdxl"),
    ("text-to-image", "someuser/dreamshaper-sd15", "sd15"),
    (None, "someuser/flux-lora-thing", None),
    (None, "someuser/totally-unknown", None),
])
def test_detect_family(pipeline_class, repo_id, expected):
    assert detect_family(pipeline_class, repo_id) == expected


def test_controlnet_repo_mapping_complete_for_supported_families():
    for family in ("sd15", "sdxl"):
        for cn_type in CONTROLNET_TYPES:
            assert controlnet_repo_for(family, cn_type), (family, cn_type)


def test_controlnet_repo_unsupported():
    assert controlnet_repo_for(None, "canny") is None
    assert controlnet_repo_for("flux", "canny") is None
    assert controlnet_repo_for("sd15", "scribble") is None


def test_supported_modes_frozen_contract():
    assert SUPPORTED_MODES == ("txt2img", "img2img", "controlnet")


# ── Image payload decoding ──────────────────────────────────────────────────

def _png_data_url(size=(8, 8)) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@needs_pil
def test_decode_valid_data_url():
    img = decode_image_payload(_png_data_url((16, 9)))
    assert img.mode == "RGB"
    assert img.size == (16, 9)


@needs_pil
def test_decode_raw_base64_without_prefix():
    raw = _png_data_url().split(",", 1)[1]
    assert decode_image_payload(raw).size == (8, 8)


@needs_pil
def test_decode_rejects_empty():
    with pytest.raises(ValueError):
        decode_image_payload("")


@needs_pil
def test_decode_rejects_bad_base64():
    with pytest.raises(ValueError, match="base64"):
        decode_image_payload("data:image/png;base64,%%%not-base64%%%")


@needs_pil
def test_decode_rejects_non_image_bytes():
    payload = base64.b64encode(b"this is not an image").decode()
    with pytest.raises(ValueError, match="format"):
        decode_image_payload(payload)


@needs_pil
def test_decode_rejects_non_image_data_url():
    with pytest.raises(ValueError, match="data URL"):
        decode_image_payload("data:text/html;base64,PGI+aGk8L2I+")


@needs_pil
def test_decode_rejects_oversized_payload():
    oversized = "A" * (MAX_INPUT_IMAGE_BYTES * 4 // 3 + 8)
    with pytest.raises(ValueError, match="volumineuse"):
        decode_image_payload(oversized)


@needs_pil
def test_canny_preprocess_shape_and_mode():
    from PIL import Image

    from services.image_gen.modes import canny_preprocess, prepare_control_image

    img = Image.new("RGB", (32, 32))
    edges = canny_preprocess(img)
    assert edges.mode == "RGB"
    assert edges.size == (32, 32)
    # prepare_control_image only preprocesses canny
    assert prepare_control_image(img, "depth", True) is img
    assert prepare_control_image(img, "canny", False) is img
    assert prepare_control_image(img, "canny", True) is not img
