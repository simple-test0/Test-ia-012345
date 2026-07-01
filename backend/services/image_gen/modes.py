"""Generation modes (txt2img / img2img / ControlNet) — pure helpers.

Everything here is importable without torch/diffusers so the routes can
validate requests cheaply and the logic stays unit-testable in the light
CI environment (PIL only).
"""
import base64
import binascii
import io
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SUPPORTED_MODES = ("txt2img", "img2img", "controlnet")
CONTROLNET_TYPES = ("canny", "depth", "pose")

# Decoded input images are capped to avoid abusive payloads (base64 inflates
# by ~4/3, so this bounds the request body at roughly 27 MB per image).
MAX_INPUT_IMAGE_BYTES = 20 * 1024 * 1024

# ControlNet checkpoints per (family, type). Only SD 1.5 and SDXL have
# broadly available checkpoints; FLUX/SD3 control models are out of scope.
_CONTROLNET_REPOS = {
    ("sd15", "canny"): "lllyasviel/control_v11p_sd15_canny",
    ("sd15", "depth"): "lllyasviel/control_v11f1p_sd15_depth",
    ("sd15", "pose"): "lllyasviel/control_v11p_sd15_openpose",
    ("sdxl", "canny"): "diffusers/controlnet-canny-sdxl-1.0",
    ("sdxl", "depth"): "diffusers/controlnet-depth-sdxl-1.0",
    ("sdxl", "pose"): "thibaud/controlnet-openpose-sdxl-1.0",
}

_DATA_URL_RE = re.compile(r"^data:image/[\w.+-]+;base64,", re.IGNORECASE)


def detect_family(pipeline_class: Optional[str], repo_id: str) -> Optional[str]:
    """Best-effort model family detection for ControlNet pairing.

    Curated models carry a diffusers pipeline_class; downloaded models only
    have an HF pipeline tag, so fall back to naming heuristics on the repo id.
    Returns "sd15", "sdxl", or None (unsupported/unknown).
    """
    pc = (pipeline_class or "").lower()
    rid = (repo_id or "").lower()

    if "flux" in pc or "flux" in rid:
        return None
    if "stablediffusion3" in pc or "stable-diffusion-3" in rid or "sd3" in rid:
        return None
    if "stablediffusionxl" in pc or "xl" in rid or "sdxl" in rid:
        return "sdxl"
    if "stablediffusion" in pc or "stable-diffusion" in rid or re.search(r"\bsd", rid):
        return "sd15"
    return None


def controlnet_repo_for(family: Optional[str], cn_type: str) -> Optional[str]:
    return _CONTROLNET_REPOS.get((family or "", cn_type))


def decode_image_payload(data: str):
    """Decode a base64 `data:` URL (or raw base64) into a PIL RGB image.

    Raises ValueError with a user-facing message on any invalid input.
    """
    from PIL import Image

    if not data or not isinstance(data, str):
        raise ValueError("Image invalide : contenu vide")

    payload = data
    if payload.startswith("data:"):
        if not _DATA_URL_RE.match(payload):
            raise ValueError("Image invalide : data URL non supportée")
        payload = payload.split(",", 1)[1]

    # Bound the base64 size before decoding (padding makes this an upper bound).
    if len(payload) * 3 // 4 > MAX_INPUT_IMAGE_BYTES:
        raise ValueError("Image trop volumineuse (max 20 Mo)")

    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Image invalide : base64 corrompu") from None

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise ValueError("Image invalide : format non reconnu") from None
    return img.convert("RGB")


def canny_preprocess(img):
    """Approximate a canny edge map with pure PIL (no cv2 dependency).

    Grayscale -> edge filter -> threshold -> RGB. Coarser than true canny but
    a workable control signal; users can also upload a pre-computed map and
    disable preprocessing.
    """
    from PIL import Image, ImageFilter, ImageOps

    gray = ImageOps.grayscale(img)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = edges.filter(ImageFilter.SMOOTH)
    binary = edges.point(lambda p: 255 if p > 32 else 0)
    return Image.merge("RGB", (binary, binary, binary))


def prepare_control_image(img, cn_type: str, preprocess: bool):
    """Return the control map to feed the ControlNet pipeline.

    Only canny has a local preprocessor; depth/pose expect the user to upload
    an already-computed control map (documented in the UI).
    """
    if preprocess and cn_type == "canny":
        return canny_preprocess(img)
    return img
