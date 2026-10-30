"""Image files on disk: saving results, thumbnails and fast step previews."""
import logging
import re
from pathlib import Path
from typing import List, Optional

from PIL import Image

from core.config import settings

logger = logging.getLogger(__name__)

THUMB_SIZE = 384
# Generated files are named "<job uuid>_<index>.png".
_FILE_RE = re.compile(r"^[0-9a-fA-F-]{36}_\d{1,2}\.png$")

# Linear approximations mapping SD latents to RGB (from ComfyUI's
# latent_formats). Decoding a preview this way costs ~nothing, whereas running
# the VAE at every step slowed generation down noticeably (a lot on CPU/MPS).
_SD15_FACTORS = [
    [0.3512, 0.2297, 0.3227],
    [0.3250, 0.4974, 0.2350],
    [-0.2829, 0.1762, 0.2721],
    [-0.2120, -0.2616, -0.7177],
]
_SDXL_FACTORS = [
    [0.3651, 0.4232, 0.4341],
    [-0.2533, -0.0042, 0.1068],
    [0.1076, 0.1111, -0.0362],
    [-0.3165, -0.2492, -0.2188],
]
_SDXL_BIAS = [0.1084, -0.0175, -0.0011]


def is_valid_image_name(name: str) -> bool:
    return bool(_FILE_RE.match(name))


def thumb_path_for(src: Path) -> Path:
    return settings.images_dir / "thumbs" / (src.stem + ".jpg")


def make_thumbnail(src: Path) -> Optional[Path]:
    """Create (or reuse) a small JPEG for the history grid."""
    dst = thumb_path_for(src)
    if dst.exists():
        return dst
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            tmp = dst.with_suffix(".tmp")
            img.save(tmp, "JPEG", quality=85, optimize=True)
            tmp.replace(dst)  # atomic: never serve a half-written file
        return dst
    except Exception as exc:
        logger.debug(f"Thumbnail failed for {src}: {exc}")
        return None


def save_images(job_id: str, images: List[Image.Image]) -> List[str]:
    """Save full-size PNGs and their thumbnails; returns the PNG paths."""
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, img in enumerate(images):
        path = settings.images_dir / f"{job_id}_{i}.png"
        img.save(path)
        make_thumbnail(path)
        paths.append(str(path))
    return paths


def image_urls(output_paths, thumbnail: bool) -> List[str]:
    """Relative API URLs for a job's images (served by /image/files)."""
    urls = []
    for p in output_paths or []:
        name = Path(p).name
        if not is_valid_image_name(name):
            continue
        suffix = "?thumb=1" if thumbnail else ""
        urls.append(f"/api/v1/image/files/{name}{suffix}")
    return urls


def delete_job_files(output_paths, init_path=None) -> None:
    if init_path:
        try:
            Path(init_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.debug(f"Could not delete {init_path}: {exc}")
    for p in output_paths or []:
        path = Path(p)
        for f in (path, thumb_path_for(path)):
            try:
                f.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug(f"Could not delete {f}: {exc}")


def latents_preview(latents, is_xl: bool, size: int = 256) -> Optional[Image.Image]:
    """Cheap RGB preview from 4-channel SD/SDXL latents (None otherwise)."""
    try:
        import numpy as np
        import torch

        if latents is None or latents.ndim != 4 or latents.shape[1] != 4:
            return None
        lat = latents[0].detach().to("cpu", dtype=torch.float32)  # (4, h, w)
        factors = torch.tensor(_SDXL_FACTORS if is_xl else _SD15_FACTORS)
        rgb = torch.einsum("chw,cr->hwr", lat, factors)
        if is_xl:
            rgb = rgb + torch.tensor(_SDXL_BIAS)
        rgb = ((rgb + 1.0) / 2.0).clamp(0, 1)
        arr = (rgb.numpy() * 255).astype(np.uint8)
        img = Image.fromarray(arr)
        scale = size / max(img.size)
        if scale > 1:
            img = img.resize(
                (int(img.width * scale), int(img.height * scale)), Image.BILINEAR
            )
        return img
    except Exception as exc:
        logger.debug(f"Latent preview failed: {exc}")
        return None


# ── img2img source images ─────────────────────────────────────────────────────

MAX_INIT_SIDE = 2048
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def init_image_path(job_id: str) -> Path:
    return settings.images_dir / "init" / f"{job_id}.png"


def save_init_image(job_id: str, data_url: str, max_w: int, max_h: int) -> tuple:
    """Decode a `data:` URL (or bare base64), fit it in max_w x max_h keeping
    its aspect ratio (multiples of 8), save it as PNG.

    Returns (path, width, height). Raises ValueError on invalid input.
    """
    import base64
    import binascii
    import io

    payload = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("init_image is not valid base64") from exc
    try:
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            img = src.convert("RGB")
    except Exception as exc:
        raise ValueError("init_image is not a readable image (PNG, JPEG, WebP…)") from exc

    scale = min(max_w / img.width, max_h / img.height, MAX_INIT_SIDE / max(img.size))
    w = max(64, int(img.width * scale) // 8 * 8)
    h = max(64, int(img.height * scale) // 8 * 8)
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)

    path = init_image_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return str(path), w, h


def init_image_url(job_id: str, path) -> Optional[str]:
    if not path or not _UUID_RE.match(job_id):
        return None
    return f"/api/v1/image/files/init/{job_id}.png"
