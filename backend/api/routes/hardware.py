from fastapi import APIRouter

from hardware.detector import detect_hardware
from hardware.recommender import recommend

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("/info")
async def hardware_info():
    hw = detect_hardware()
    return {
        "cuda_available": hw.cuda_available,
        "platform": hw.platform,
        "gpus": [
            {
                "index": g.index,
                "name": g.name,
                "vram_total_mb": g.vram_total_mb,
                "vram_used_mb": g.vram_used_mb,
                "vram_free_mb": g.vram_free_mb,
                "utilization_percent": g.utilization_percent,
                "compute_capability": g.compute_capability,
                "cuda_version": g.cuda_version,
                "driver_version": g.driver_version,
            }
            for g in hw.gpus
        ],
        "ram_total_mb": hw.ram_total_mb,
        "ram_used_mb": hw.ram_used_mb,
        "ram_free_mb": hw.ram_free_mb,
        "cpu": {
            "name": hw.cpu.name,
            "physical_cores": hw.cpu.physical_cores,
            "logical_cores": hw.cpu.logical_cores,
            "utilization_percent": hw.cpu.utilization_percent,
            "frequency_mhz": hw.cpu.frequency_mhz,
        } if hw.cpu else None,
    }


@router.get("/recommendations")
async def hardware_recommendations():
    hw = detect_hardware()
    rec = recommend(hw)
    return {
        "tier_label": rec.tier_label,
        "vram_mb": rec.vram_mb,
        "ram_mb": rec.ram_mb,
        "cpu_cores": rec.cpu_cores,
        "image_gen": {
            "recommended_models": rec.image_gen.recommended_models,
            "max_resolution": list(rec.image_gen.max_resolution),
            "recommended_steps": rec.image_gen.recommended_steps,
            "cfg_scale": rec.image_gen.cfg_scale,
            "enable_xformers": rec.image_gen.enable_xformers,
            "enable_attention_slicing": rec.image_gen.enable_attention_slicing,
            "enable_cpu_offload": rec.image_gen.enable_cpu_offload,
            "use_fp16": rec.image_gen.use_fp16,
            "notes": rec.image_gen.notes,
        },
        "training": {
            "recommended_batch_size": rec.training.recommended_batch_size,
            "recommended_learning_rate": rec.training.recommended_learning_rate,
            "num_dataloader_workers": rec.training.num_dataloader_workers,
            "use_mixed_precision": rec.training.use_mixed_precision,
            "gradient_accumulation_steps": rec.training.gradient_accumulation_steps,
            "max_recommended_params": rec.training.max_recommended_params,
            "recommended_architectures": rec.training.recommended_architectures,
            "notes": rec.training.notes,
        },
        "agent": {
            "recommended_models": rec.agent.recommended_models,
            "context_window_tokens": rec.agent.context_window_tokens,
            "quantization": rec.agent.quantization,
            "notes": rec.agent.notes,
        },
    }
