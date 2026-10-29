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


def delete_job_files(output_paths) -> None:
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
