"""Hardware detection.

Vendor-agnostic accelerator detection. Supports, in priority order:

* NVIDIA CUDA          (``torch.cuda`` with ``torch.version.hip is None``)
* AMD ROCm / HIP       (``torch.cuda`` with ``torch.version.hip`` set)
* Intel XPU            (``torch.xpu``)
* Apple Silicon MPS    (``torch.backends.mps``)
* CPU                  (always available fallback)

The result is cached for a short TTL so that hot paths (``/hardware/info``,
pipeline loading, per-request VRAM checks) do not repeatedly pay the cost of
importing torch or sampling CPU utilisation. Dynamic fields (free VRAM, CPU
load) are refreshed on each rebuild; nothing here ever raises — every probe is
wrapped and degrades gracefully so the rest of the app keeps working on exotic
or partially-supported machines.
"""

from __future__ import annotations

import contextlib
import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import psutil

logger = logging.getLogger(__name__)

# Backend identifiers used across the whole backend as the single source of
# truth for "what kind of accelerator am I talking to".
BACKEND_CUDA = "cuda"
BACKEND_ROCM = "rocm"
BACKEND_XPU = "xpu"
BACKEND_MPS = "mps"
BACKEND_CPU = "cpu"

# How long a detection snapshot stays valid (seconds). Short enough that the UI
# feels live, long enough to absorb bursts of requests cheaply.
_CACHE_TTL_SECONDS = 2.0


@dataclass
class GPUInfo:
    index: int
    name: str
    vram_total_mb: int
    vram_used_mb: int
    vram_free_mb: int
    utilization_percent: float
    compute_capability: str
    cuda_version: str
    driver_version: str
    # New, vendor-agnostic fields. ``backend`` is one of the BACKEND_* constants
    # and ``device_str`` is the exact string to hand to ``tensor.to(...)``.
    backend: str = BACKEND_CUDA
    device_str: str = "cuda:0"
    is_unified_memory: bool = False


@dataclass
class CPUInfo:
    name: str
    physical_cores: int
    logical_cores: int
    utilization_percent: float
    frequency_mhz: float


@dataclass
class HardwareInfo:
    gpus: List[GPUInfo] = field(default_factory=list)
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    ram_free_mb: int = 0
    cpu: Optional[CPUInfo] = None
    platform: str = ""
    # ``cuda_available`` is kept for backward compatibility (it is true for both
    # CUDA and ROCm, since ROCm masquerades as CUDA in torch). Prefer the richer
    # ``accelerator_available`` / ``accelerator_backend`` for new code.
    cuda_available: bool = False
    accelerator_available: bool = False
    accelerator_backend: str = BACKEND_CPU
    torch_available: bool = False
    torch_version: str = ""

    @property
    def primary_gpu(self) -> Optional[GPUInfo]:
        return self.gpus[0] if self.gpus else None

    @property
    def total_vram_mb(self) -> int:
        """Sum of dedicated VRAM across discrete accelerators (0 for CPU/unified)."""
        return sum(g.vram_total_mb for g in self.gpus if not g.is_unified_memory)


# ── Internal cache ──────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cached_info: Optional[HardwareInfo] = None
_cached_at: float = 0.0

# Prime psutil's CPU sampler once so later non-blocking reads return real data
# instead of 0.0 (the first ever call always returns 0.0 with interval=None).
try:
    psutil.cpu_percent(interval=None)
except Exception:  # pragma: no cover - psutil should always work
    logger.debug("Could not prime psutil.cpu_percent", exc_info=True)


def detect_hardware(force_refresh: bool = False) -> HardwareInfo:
    """Return a (cached) hardware snapshot.

    Thread-safe and side-effect free. Pass ``force_refresh=True`` to bypass the
    TTL cache (e.g. right after loading/unloading a large model).
    """
    global _cached_info, _cached_at
    now = time.monotonic()
    if not force_refresh and _cached_info is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_info

    with _cache_lock:
        # Re-check after acquiring the lock to avoid a thundering herd.
        now = time.monotonic()
        if not force_refresh and _cached_info is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return _cached_info

        info = _build_hardware_info()
        _cached_info = info
        _cached_at = time.monotonic()
        return info


def _build_hardware_info() -> HardwareInfo:
    info = HardwareInfo(platform=f"{platform.system()} {platform.machine()}".strip())
    _detect_memory(info)
    _detect_cpu(info)
    _detect_accelerators(info)
    return info


def _detect_memory(info: HardwareInfo) -> None:
    try:
        vm = psutil.virtual_memory()
        info.ram_total_mb = vm.total // (1024**2)
        info.ram_used_mb = vm.used // (1024**2)
        info.ram_free_mb = vm.available // (1024**2)
    except Exception:
        logger.warning("RAM detection failed", exc_info=True)


def _detect_cpu(info: HardwareInfo) -> None:
    try:
        freq = psutil.cpu_freq()
    except Exception:
        freq = None
    try:
        info.cpu = CPUInfo(
            name=_cpu_name(),
            physical_cores=psutil.cpu_count(logical=False) or 1,
            logical_cores=psutil.cpu_count(logical=True) or 1,
            # interval=None is non-blocking (uses the delta since the last call)
            # instead of pinning the request for 100ms.
            utilization_percent=psutil.cpu_percent(interval=None),
            frequency_mhz=freq.current if freq else 0.0,
        )
    except Exception:
        logger.warning("CPU detection failed", exc_info=True)


def _cpu_name() -> str:
    """Best-effort human-readable CPU name across platforms."""
    name = platform.processor()
    if name:
        return name
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        logger.debug("Could not read /proc/cpuinfo", exc_info=True)
    return platform.machine() or "Unknown CPU"


def _detect_accelerators(info: HardwareInfo) -> None:
    try:
        import torch
    except ImportError:
        logger.info("torch not installed — running in CPU-only mode")
        return

    info.torch_available = True
    info.torch_version = getattr(torch, "__version__", "")

    # CUDA covers both NVIDIA (hip is None) and AMD ROCm (hip set). torch exposes
    # ROCm devices through the same torch.cuda API.
    is_rocm = bool(getattr(torch.version, "hip", None))
    try:
        cuda_ok = torch.cuda.is_available()
    except Exception:
        cuda_ok = False
        logger.debug("torch.cuda.is_available() raised", exc_info=True)

    if cuda_ok:
        backend = BACKEND_ROCM if is_rocm else BACKEND_CUDA
        info.cuda_available = True
        info.accelerator_available = True
        info.accelerator_backend = backend
        _detect_cuda_like(info, torch, backend)
        return

    # Intel discrete / integrated GPUs via the XPU backend.
    if _xpu_available(torch):
        info.accelerator_available = True
        info.accelerator_backend = BACKEND_XPU
        _detect_xpu(info, torch)
        return

    # Apple Silicon (unified memory). No per-device VRAM — budget comes from RAM.
    if _mps_available(torch):
        info.accelerator_available = True
        info.accelerator_backend = BACKEND_MPS
        _detect_mps(info, torch)
        return

    logger.info("No supported accelerator found — CPU-only mode")


def _detect_cuda_like(info: HardwareInfo, torch, backend: str) -> None:
    try:
        device_count = torch.cuda.device_count()
    except Exception:
        logger.warning("Could not enumerate %s devices", backend, exc_info=True)
        return

    # Optional richer telemetry (driver version, live utilisation). Only NVIDIA
    # exposes this cleanly; failures are non-fatal.
    gputil_gpus = _try_gputil()

    for i in range(device_count):
        try:
            props = torch.cuda.get_device_properties(i)
            vram_total = props.total_memory // (1024**2)
            try:
                free_bytes, _ = torch.cuda.mem_get_info(i)
                vram_free = free_bytes // (1024**2)
            except Exception:
                vram_free = vram_total
            vram_used = max(0, vram_total - vram_free)

            driver_ver = "unknown"
            util_pct = 0.0
            if gputil_gpus and i < len(gputil_gpus):
                driver_ver = gputil_gpus[i].driver or "unknown"
                util_pct = round(gputil_gpus[i].load * 100, 1)

            info.gpus.append(
                GPUInfo(
                    index=i,
                    name=props.name,
                    vram_total_mb=vram_total,
                    vram_used_mb=vram_used,
                    vram_free_mb=vram_free,
                    utilization_percent=util_pct,
                    compute_capability=f"{props.major}.{props.minor}",
                    cuda_version=(
                        getattr(torch.version, "hip", None) if backend == BACKEND_ROCM else torch.version.cuda
                    )
                    or "unknown",
                    driver_version=driver_ver,
                    backend=backend,
                    device_str=f"cuda:{i}",
                )
            )
        except Exception:
            logger.warning("Failed to read %s device %d", backend, i, exc_info=True)


def _detect_xpu(info: HardwareInfo, torch) -> None:
    try:
        device_count = torch.xpu.device_count()
    except Exception:
        logger.warning("Could not enumerate XPU devices", exc_info=True)
        return

    for i in range(device_count):
        try:
            props = torch.xpu.get_device_properties(i)
            vram_total = getattr(props, "total_memory", 0) // (1024**2)
            vram_free = vram_total
            try:
                free_bytes, _ = torch.xpu.mem_get_info(i)
                vram_free = free_bytes // (1024**2)
            except Exception:
                pass
            info.gpus.append(
                GPUInfo(
                    index=i,
                    name=getattr(props, "name", f"Intel XPU {i}"),
                    vram_total_mb=vram_total,
                    vram_used_mb=max(0, vram_total - vram_free),
                    vram_free_mb=vram_free,
                    utilization_percent=0.0,
                    compute_capability="xpu",
                    cuda_version="n/a",
                    driver_version=getattr(props, "driver_version", "unknown"),
                    backend=BACKEND_XPU,
                    device_str=f"xpu:{i}",
                )
            )
        except Exception:
            logger.warning("Failed to read XPU device %d", i, exc_info=True)


def _detect_mps(info: HardwareInfo, torch) -> None:
    # Apple Silicon shares memory between CPU and GPU. Use torch's recommended
    # working-set size when available, otherwise budget ~70% of system RAM.
    budget_mb = 0
    try:
        budget_mb = int(torch.mps.recommended_max_memory() // (1024**2))
    except Exception:
        logger.debug("torch.mps.recommended_max_memory unavailable", exc_info=True)
    if budget_mb <= 0:
        budget_mb = int(info.ram_total_mb * 0.7)

    used_mb = 0
    with contextlib.suppress(Exception):
        used_mb = int(torch.mps.current_allocated_memory() // (1024**2))

    info.gpus.append(
        GPUInfo(
            index=0,
            name=f"Apple Silicon GPU ({platform.machine()})",
            vram_total_mb=budget_mb,
            vram_used_mb=used_mb,
            vram_free_mb=max(0, budget_mb - used_mb),
            utilization_percent=0.0,
            compute_capability="mps",
            cuda_version="n/a",
            driver_version=platform.mac_ver()[0] or "unknown",
            backend=BACKEND_MPS,
            device_str="mps",
            is_unified_memory=True,
        )
    )


def _xpu_available(torch) -> bool:
    try:
        return hasattr(torch, "xpu") and torch.xpu.is_available()
    except Exception:
        return False


def _mps_available(torch) -> bool:
    try:
        return torch.backends.mps.is_available()
    except Exception:
        return False


def _try_gputil():
    try:
        import GPUtil

        return GPUtil.getGPUs()
    except Exception:
        logger.debug("GPUtil telemetry unavailable", exc_info=True)
        return None


# ── Convenience helpers used across services ─────────────────────────────────
def get_primary_vram_mb() -> int:
    """VRAM (MB) of the primary accelerator, or 0 on CPU-only machines.

    For unified-memory devices (Apple Silicon) this returns the usable memory
    budget rather than 0, so capability checks behave sensibly.
    """
    hw = detect_hardware()
    gpu = hw.primary_gpu
    return gpu.vram_total_mb if gpu else 0


def get_memory_budget_mb() -> int:
    """Usable memory budget for sizing models, regardless of backend.

    Discrete accelerator → its VRAM. Otherwise → ~70% of system RAM (the amount
    safely usable for CPU inference without thrashing).
    """
    hw = detect_hardware()
    gpu = hw.primary_gpu
    if gpu:
        return gpu.vram_total_mb
    return int(hw.ram_total_mb * 0.7)


def get_torch_device(prefer: Optional[str] = None) -> str:
    """Return the best ``tensor.to(...)`` device string for this machine.

    ``prefer`` may force a backend (e.g. ``"cpu"`` or ``"cuda:1"``); it is honoured
    only if actually available, otherwise we fall back to autodetection.
    """
    if prefer:
        prefer = prefer.strip().lower()
        if prefer == BACKEND_CPU:
            return "cpu"
        hw = detect_hardware()
        for gpu in hw.gpus:
            if prefer in (gpu.backend, gpu.device_str):
                return gpu.device_str
        logger.warning("Preferred device '%s' not available; autodetecting", prefer)

    hw = detect_hardware()
    gpu = hw.primary_gpu
    return gpu.device_str if gpu else "cpu"


def empty_accelerator_cache() -> None:
    """Release cached accelerator memory in a backend-agnostic way. Never raises."""
    try:
        import torch
    except ImportError:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif _xpu_available(torch):
            torch.xpu.empty_cache()
        elif _mps_available(torch):
            torch.mps.empty_cache()
    except Exception:
        logger.debug("empty_accelerator_cache failed", exc_info=True)
