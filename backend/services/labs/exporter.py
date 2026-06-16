import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def export_model(
    checkpoint_path: str,
    arch_id: str,
    arch_config: Dict[str, Any],
    export_format: str,
    output_dir: str,
) -> str:
    """Export a trained model checkpoint to ONNX or safetensors format."""

    def _export() -> str:
        import torch
        from services.labs.architecture_registry import get_arch

        spec = get_arch(arch_id)
        if spec is None:
            raise ValueError(f"Unknown architecture: {arch_id}")

        model = spec.builder(arch_config)
        ckpt = torch.load(checkpoint_path, map_location="cpu")
        model.load_state_dict(ckpt["model_state"])
        model.eval()

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if export_format == "onnx":
            out_path = str(out_dir / "model.onnx")
            dummy = _make_dummy_input(arch_id, arch_config)
            torch.onnx.export(
                model,
                dummy,
                out_path,
                opset_version=17,
                input_names=["input"],
                output_names=["output"],
                dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
            )
            return out_path

        elif export_format == "safetensors":
            from safetensors.torch import save_file
            out_path = str(out_dir / "model.safetensors")
            tensors = {k: v.contiguous() for k, v in model.state_dict().items()}
            save_file(tensors, out_path)
            return out_path

        else:
            raise ValueError(f"Unsupported format: {export_format}")

    return await asyncio.get_event_loop().run_in_executor(None, _export)


def _make_dummy_input(arch_id: str, arch_config: dict):
    import torch

    if arch_id in ("rnn", "lstm", "gru"):
        seq_len = arch_config.get("max_seq_len", 128)
        vocab_size = arch_config.get("vocab_size", 10000)
        return torch.randint(0, vocab_size, (1, seq_len))
    elif arch_id == "transformer":
        seq_len = arch_config.get("max_seq_len", 512)
        vocab_size = arch_config.get("vocab_size", 50257)
        return torch.randint(0, vocab_size, (1, seq_len))
    else:
        img_size = arch_config.get("image_size", 32)
        in_ch = arch_config.get("in_channels", 3)
        return torch.randn(1, in_ch, img_size, img_size)
