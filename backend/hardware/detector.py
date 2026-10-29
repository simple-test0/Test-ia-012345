import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import psutil

logger = logging.getLogger(__name__)


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
    cuda_available: bool = False
    # Apple Silicon GPU (Metal). Memory is unified with system RAM.
    mps_available: bool = False

    @property
    def accelerator(self) -> str:
        if self.cuda_available:
            return "cuda"
        if self.mps_available:
            return "mps"
        return "cpu"


def detect_hardware() -> HardwareInfo:
    info = HardwareInfo(platform=platform.system())

    # RAM
    vm = psutil.virtual_memory()
    info.ram_total_mb = vm.total // (1024 ** 2)
    info.ram_used_mb = vm.used // (1024 ** 2)
    info.ram_free_mb = vm.available // (1024 ** 2)

    # CPU
    freq = psutil.cpu_freq()
    info.cpu = CPUInfo(
        name=platform.processor() or platform.machine() or "Unknown",
        physical_cores=psutil.cpu_count(logical=False) or 1,
        logical_cores=psutil.cpu_count(logical=True) or 1,
        # interval=None is non-blocking (usage since the previous call).
        utilization_percent=psutil.cpu_percent(interval=None),
        frequency_mhz=freq.current if freq else 0.0,
    )

    # GPU / CUDA
    try:
        import torch

        info.cuda_available = torch.cuda.is_available()
        try:
            info.mps_available = (
                not info.cuda_available and torch.backends.mps.is_available()
            )
        except Exception:
            info.mps_available = False
        gputil_gpus = []
        if info.cuda_available:
            try:
                import GPUtil

                gputil_gpus = GPUtil.getGPUs()
            except Exception as exc:
                logger.debug(f"GPUtil unavailable: {exc}")
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                vram_total = props.total_memory // (1024 ** 2)
                free_bytes, _ = torch.cuda.mem_get_info(i)
                vram_free = free_bytes // (1024 ** 2)
                vram_used = vram_total - vram_free

                driver_ver = "unknown"
                util_pct = 0.0
                if i < len(gputil_gpus):
                    driver_ver = gputil_gpus[i].driver
                    util_pct = gputil_gpus[i].load * 100

                info.gpus.append(
                    GPUInfo(
                        index=i,
                        name=props.name,
                        vram_total_mb=vram_total,
                        vram_used_mb=vram_used,
                        vram_free_mb=vram_free,
                        utilization_percent=util_pct,
                        compute_capability=f"{props.major}.{props.minor}",
                        cuda_version=torch.version.cuda or "unknown",
                        driver_version=driver_ver,
                    )
                )
    except ImportError:
        pass

    return info


# ── Caching ──────────────────────────────────────────────────────────────────
# detect_hardware() blocks ~0.1s on psutil.cpu_percent and is hit by /models and
# frequent polling, so cache the full snapshot briefly.
_HW_CACHE: dict = {"value": None, "ts": 0.0}
_HW_TTL = 2.0
_HW_LOCK = threading.Lock()
_VRAM_CACHE: Optional[int] = None


def detect_hardware_cached() -> HardwareInfo:
    with _HW_LOCK:
        now = time.monotonic()
        if _HW_CACHE["value"] is None or (now - _HW_CACHE["ts"]) > _HW_TTL:
            _HW_CACHE["value"] = detect_hardware()
            _HW_CACHE["ts"] = time.monotonic()
        return _HW_CACHE["value"]


def effective_vram_mb(hw: HardwareInfo) -> int:
    """Memory usable by the accelerator, in MB.

    CUDA: VRAM of the first GPU. Apple Silicon (MPS): unified memory, of which
    macOS lets the GPU use roughly two thirds. CPU only: 0.
    """
    if hw.gpus:
        return hw.gpus[0].vram_total_mb
    if hw.mps_available:
        return int(hw.ram_total_mb * 0.65)
    return 0


def get_primary_vram_mb() -> int:
    # Total VRAM never changes during a run — compute once.
    global _VRAM_CACHE
    if _VRAM_CACHE is None:
        _VRAM_CACHE = effective_vram_mb(detect_hardware_cached())
    return _VRAM_CACHE
