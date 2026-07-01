from hardware.detector import CPUInfo, GPUInfo, HardwareInfo
from hardware.recommender import recommend


def _hw(vram_mb: int) -> HardwareInfo:
    gpus = []
    if vram_mb:
        gpus.append(GPUInfo(
            index=0, name="Test", vram_total_mb=vram_mb, vram_used_mb=0,
            vram_free_mb=vram_mb, utilization_percent=0.0, compute_capability="8.6",
            cuda_version="12.1", driver_version="x",
        ))
    return HardwareInfo(
        gpus=gpus, ram_total_mb=16000, ram_used_mb=0, ram_free_mb=16000,
        cpu=CPUInfo(name="cpu", physical_cores=4, logical_cores=8,
                    utilization_percent=0.0, frequency_mhz=3000.0),
        platform="Linux", cuda_available=bool(vram_mb),
    )


def test_low_vram_tier_uses_sd15_and_offload():
    rec = recommend(_hw(2000))
    assert rec.image_gen.recommended_models == ["sd15"]
    assert rec.image_gen.enable_cpu_offload is True
    assert rec.training.recommended_batch_size >= 1


def test_high_vram_tier_includes_flux_and_sane_training():
    rec = recommend(_hw(24000))
    assert "flux-schnell" in rec.image_gen.recommended_models
    assert rec.training.recommended_batch_size >= 1
    assert "vit" in rec.training.recommended_architectures


def test_16gb_tier_fits_rtx_4060_ti_16gb():
    # An RTX 4060 Ti 16GB reports ~16.3 GB: FLUX (~22GB) and 70B LLMs must NOT
    # be recommended, but full SDXL should be.
    rec = recommend(_hw(16380))
    assert "flux-schnell" not in rec.image_gen.recommended_models
    assert "sdxl" in rec.image_gen.recommended_models
    assert not any("70b" in m for m in rec.agent.recommended_models)


def test_8gb_tier_recommends_sdxl_turbo():
    # An RTX 4060 Ti 8GB reports ~8.1 GB total.
    rec = recommend(_hw(8188))
    assert "sdxl-turbo" in rec.image_gen.recommended_models
    assert rec.image_gen.cfg_scale == 0.0 or rec.image_gen.recommended_steps <= 10


def test_cpu_only_tier():
    rec = recommend(_hw(0))
    assert rec.vram_mb == 0
    assert rec.image_gen.recommended_models  # still recommends something
    assert "CPU" in rec.tier_label or rec.vram_mb == 0
