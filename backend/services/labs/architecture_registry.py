from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from services.labs.architectures.cnn import build_cnn
from services.labs.architectures.pretrained import BACKBONES, build_pretrained
from services.labs.architectures.rnn import build_gru, build_lstm, build_rnn
from services.labs.architectures.transformer import build_transformer
from services.labs.architectures.vit import build_vit


@dataclass
class ArchitectureSpec:
    id: str
    name: str
    description: str
    builder: Callable
    default_config: Dict[str, Any]
    task_types: List[str]
    min_vram_mb: int
    param_schema: Dict[str, Any]
    tags: List[str] = field(default_factory=list)


# CLAUDE: add new architectures here — import builder above, add ArchitectureSpec entry
ARCHITECTURE_REGISTRY: Dict[str, ArchitectureSpec] = {
    "pretrained": ArchitectureSpec(
        id="pretrained",
        name="Transfer Learning (pretrained backbone)",
        description=(
            "Start from an ImageNet-pretrained backbone and retrain only the "
            "classifier head — the fastest path to strong image-classification "
            "results on consumer GPUs. Unfreeze the backbone later to fine-tune."
        ),
        builder=build_pretrained,
        default_config={
            "backbone": "efficientnet_v2_s",
            "num_classes": 10,
            "in_channels": 3,
            "image_size": 224,
            "pretrained": True,
            "freeze_backbone": True,
        },
        task_types=["classification"],
        min_vram_mb=2048,
        param_schema={
            "backbone": {
                "type": "select",
                "options": list(BACKBONES.keys()),
                "label": "Pretrained backbone",
            },
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Number of classes"},
            "freeze_backbone": {"type": "boolean", "label": "Freeze backbone (head-only training)"},
            "pretrained": {"type": "boolean", "label": "Use ImageNet weights"},
        },
        tags=["image", "transfer-learning", "recommended", "modern"],
    ),
    "cnn": ArchitectureSpec(
        id="cnn",
        name="Convolutional Neural Network (CNN)",
        description="Image feature extraction via convolutional layers. Best for image classification and detection tasks.",
        builder=build_cnn,
        default_config={
            "num_classes": 10,
            "in_channels": 3,
            "layers": [
                {"type": "conv", "out_channels": 32, "kernel_size": 3, "padding": 1},
                {"type": "bn"},
                {"type": "relu"},
                {"type": "pool"},
                {"type": "conv", "out_channels": 64, "kernel_size": 3, "padding": 1},
                {"type": "bn"},
                {"type": "relu"},
                {"type": "pool"},
                {"type": "flatten"},
                {"type": "fc", "out_features": 256},
                {"type": "relu"},
                {"type": "dropout", "p": 0.5},
            ],
        },
        task_types=["classification", "detection"],
        min_vram_mb=512,
        param_schema={
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Number of classes"},
            "in_channels": {"type": "integer", "min": 1, "max": 4, "label": "Input channels (1=gray, 3=RGB)"},
        },
        tags=["image", "classification", "classic"],
    ),
    "rnn": ArchitectureSpec(
        id="rnn",
        name="Recurrent Neural Network (RNN)",
        description="Sequential data processing with recurrent connections. Suitable for NLP and time-series.",
        builder=build_rnn,
        default_config={
            "vocab_size": 10000,
            "embed_dim": 128,
            "hidden_size": 256,
            "num_layers": 2,
            "num_classes": 10,
            "dropout": 0.3,
            "bidirectional": False,
        },
        task_types=["nlp", "classification"],
        min_vram_mb=512,
        param_schema={
            "vocab_size": {"type": "integer", "min": 100, "max": 200000, "label": "Vocabulary size"},
            "embed_dim": {"type": "integer", "min": 32, "max": 1024, "label": "Embedding dimension"},
            "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
            "num_layers": {"type": "integer", "min": 1, "max": 8, "label": "Number of layers"},
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Output classes"},
            "dropout": {"type": "float", "min": 0.0, "max": 0.9, "label": "Dropout rate"},
            "bidirectional": {"type": "boolean", "label": "Bidirectional"},
        },
        tags=["nlp", "sequential", "text"],
    ),
    "lstm": ArchitectureSpec(
        id="lstm",
        name="Long Short-Term Memory (LSTM)",
        description="Advanced RNN with gating mechanisms. Better gradient flow for longer sequences.",
        builder=build_lstm,
        default_config={
            "vocab_size": 10000,
            "embed_dim": 128,
            "hidden_size": 256,
            "num_layers": 2,
            "num_classes": 10,
            "dropout": 0.3,
            "bidirectional": True,
        },
        task_types=["nlp", "classification"],
        min_vram_mb=512,
        param_schema={
            "vocab_size": {"type": "integer", "min": 100, "max": 200000, "label": "Vocabulary size"},
            "embed_dim": {"type": "integer", "min": 32, "max": 1024, "label": "Embedding dimension"},
            "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
            "num_layers": {"type": "integer", "min": 1, "max": 8, "label": "Number of layers"},
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Output classes"},
            "dropout": {"type": "float", "min": 0.0, "max": 0.9, "label": "Dropout rate"},
            "bidirectional": {"type": "boolean", "label": "Bidirectional"},
        },
        tags=["nlp", "sequential", "text"],
    ),
    "gru": ArchitectureSpec(
        id="gru",
        name="Gated Recurrent Unit (GRU)",
        description="Efficient variant of LSTM with fewer parameters. Trains faster with similar performance.",
        builder=build_gru,
        default_config={
            "vocab_size": 10000,
            "embed_dim": 128,
            "hidden_size": 256,
            "num_layers": 2,
            "num_classes": 10,
            "dropout": 0.3,
            "bidirectional": True,
        },
        task_types=["nlp", "classification"],
        min_vram_mb=512,
        param_schema={
            "vocab_size": {"type": "integer", "min": 100, "max": 200000, "label": "Vocabulary size"},
            "embed_dim": {"type": "integer", "min": 32, "max": 1024, "label": "Embedding dimension"},
            "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
            "num_layers": {"type": "integer", "min": 1, "max": 8, "label": "Number of layers"},
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Output classes"},
            "dropout": {"type": "float", "min": 0.0, "max": 0.9, "label": "Dropout rate"},
            "bidirectional": {"type": "boolean", "label": "Bidirectional"},
        },
        tags=["nlp", "sequential", "efficient"],
    ),
    "transformer": ArchitectureSpec(
        id="transformer",
        name="Transformer (Encoder)",
        description="Attention-based architecture. State-of-the-art for NLP tasks, scalable to large sizes.",
        builder=build_transformer,
        default_config={
            "vocab_size": 50257,
            "n_embd": 256,
            "n_head": 8,
            "n_layer": 6,
            "max_seq_len": 512,
            "dropout": 0.1,
            "num_classes": 4,
        },
        task_types=["nlp", "classification"],
        min_vram_mb=2048,
        param_schema={
            "vocab_size": {"type": "integer", "min": 1000, "max": 200000, "label": "Vocabulary size"},
            "n_embd": {"type": "integer", "min": 64, "max": 2048, "label": "Embedding dimension"},
            "n_head": {"type": "integer", "min": 1, "max": 32, "label": "Attention heads"},
            "n_layer": {"type": "integer", "min": 1, "max": 48, "label": "Transformer layers"},
            "max_seq_len": {"type": "integer", "min": 64, "max": 8192, "label": "Max sequence length"},
            "dropout": {"type": "float", "min": 0.0, "max": 0.5, "label": "Dropout rate"},
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Number of classes"},
        },
        tags=["nlp", "attention", "scalable"],
    ),
    "vit": ArchitectureSpec(
        id="vit",
        name="Vision Transformer (ViT)",
        description="Transformer applied to image patches. Strong for image classification at scale.",
        builder=build_vit,
        default_config={
            "image_size": 224,
            "patch_size": 16,
            "num_classes": 10,
            "dim": 512,
            "depth": 6,
            "heads": 8,
            "mlp_dim": 1024,
            "dropout": 0.1,
            "in_channels": 3,
        },
        task_types=["classification"],
        min_vram_mb=3072,
        param_schema={
            "image_size": {"type": "integer", "min": 32, "max": 1024, "label": "Input image size (px)"},
            "patch_size": {"type": "integer", "min": 8, "max": 64, "label": "Patch size (px)"},
            "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Number of classes"},
            "dim": {"type": "integer", "min": 64, "max": 2048, "label": "Embedding dimension"},
            "depth": {"type": "integer", "min": 1, "max": 48, "label": "Transformer depth"},
            "heads": {"type": "integer", "min": 1, "max": 32, "label": "Attention heads"},
            "mlp_dim": {"type": "integer", "min": 128, "max": 8192, "label": "MLP dimension"},
            "dropout": {"type": "float", "min": 0.0, "max": 0.5, "label": "Dropout rate"},
        },
        tags=["image", "attention", "classification"],
    ),
}


def get_arch(arch_id: str) -> Optional[ArchitectureSpec]:
    return ARCHITECTURE_REGISTRY.get(arch_id)


def list_archs(vram_mb: int = 0, task_type: str = "") -> List[ArchitectureSpec]:
    results = list(ARCHITECTURE_REGISTRY.values())
    if vram_mb > 0:
        results = [a for a in results if a.min_vram_mb <= vram_mb]
    if task_type:
        results = [a for a in results if task_type in a.task_types]
    return results


def count_parameters(model) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
