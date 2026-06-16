"""Transfer-learning architecture: pretrained torchvision backbones.

The modern, consumer-GPU-friendly way to get strong results fast — start from a
backbone pretrained on ImageNet and only retrain (or fine-tune) the classifier
head. Far cheaper than training from scratch, which is exactly what a 6-24 GB
card wants.

Backbones are chosen to span the speed/quality range that fits consumer VRAM:
MobileNetV3 (tiny), EfficientNetV2-S and ConvNeXt-Tiny (modern, efficient),
ResNet-50 (classic baseline) and ViT-B/16 (transformer).
"""
from typing import Any, Dict

import torch.nn as nn

# name → (torchvision model id, approx params for the UI)
BACKBONES = {
    "mobilenet_v3_large": "mobilenet_v3_large",
    "efficientnet_v2_s": "efficientnet_v2_s",
    "convnext_tiny": "convnext_tiny",
    "resnet50": "resnet50",
    "vit_b_16": "vit_b_16",
}


def build_pretrained(config: Dict[str, Any]) -> nn.Module:
    import torchvision

    backbone = config.get("backbone", "efficientnet_v2_s")
    if backbone not in BACKBONES:
        backbone = "efficientnet_v2_s"
    num_classes = int(config.get("num_classes", 10))
    pretrained = bool(config.get("pretrained", True))
    freeze_backbone = bool(config.get("freeze_backbone", True))

    weights = "DEFAULT" if pretrained else None
    model = torchvision.models.get_model(BACKBONES[backbone], weights=weights)

    if freeze_backbone:
        for p in model.parameters():
            p.requires_grad = False

    _replace_classifier(model, num_classes)
    return model


def _replace_classifier(model: nn.Module, num_classes: int) -> None:
    """Swap the final classification layer for a fresh ``num_classes`` head.

    Handles the head conventions of the supported families and falls back to
    replacing the last ``nn.Linear`` anywhere in the model. The new head's
    parameters always require grad, even when the backbone is frozen.
    """
    # ResNet / RegNet / ResNeXt: model.fc
    if isinstance(getattr(model, "fc", None), nn.Linear):
        model.fc = nn.Linear(model.fc.in_features, num_classes)
        return

    # ViT: model.heads.head
    heads = getattr(model, "heads", None)
    if heads is not None and isinstance(getattr(heads, "head", None), nn.Linear):
        heads.head = nn.Linear(heads.head.in_features, num_classes)
        return

    # EfficientNet / MobileNet / ConvNeXt: model.classifier is a Sequential whose
    # last Linear is the head (or classifier itself is a Linear).
    classifier = getattr(model, "classifier", None)
    if isinstance(classifier, nn.Linear):
        model.classifier = nn.Linear(classifier.in_features, num_classes)
        return
    if isinstance(classifier, nn.Sequential):
        for i in range(len(classifier) - 1, -1, -1):
            if isinstance(classifier[i], nn.Linear):
                classifier[i] = nn.Linear(classifier[i].in_features, num_classes)
                return

    # Generic fallback: replace the last Linear found in the module tree.
    last_name, last_linear = None, None
    for name, module in model.named_modules():
        if isinstance(module, nn.Linear):
            last_name, last_linear = name, module
    if last_linear is None:
        raise ValueError("Could not locate a classifier head to replace")
    parent = model
    *path, attr = last_name.split(".")
    for p in path:
        parent = getattr(parent, p)
    setattr(parent, attr, nn.Linear(last_linear.in_features, num_classes))
