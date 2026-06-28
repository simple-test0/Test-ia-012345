from typing import Any

import torch.nn as nn


def build_cnn(config: dict[str, Any]) -> nn.Module:
    num_classes = config.get("num_classes", 10)
    in_channels = config.get("in_channels", 3)
    layers_cfg = config.get(
        "layers",
        [
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
    )

    layers: list[nn.Module] = []
    current_channels = in_channels

    for layer in layers_cfg:
        ltype = layer["type"]
        if ltype == "conv":
            out_ch = layer.get("out_channels", 32)
            ks = layer.get("kernel_size", 3)
            padding = layer.get("padding", 1)
            layers.append(nn.Conv2d(current_channels, out_ch, ks, padding=padding))
            current_channels = out_ch
        elif ltype == "bn":
            layers.append(nn.BatchNorm2d(current_channels))
        elif ltype == "relu":
            layers.append(nn.ReLU(inplace=True))
        elif ltype == "pool":
            layers.append(nn.MaxPool2d(2, 2))
        elif ltype == "avgpool":
            layers.append(nn.AdaptiveAvgPool2d((1, 1)))
        elif ltype == "flatten":
            layers.append(nn.AdaptiveAvgPool2d((4, 4)))
            layers.append(nn.Flatten())
            current_channels = current_channels * 4 * 4
        elif ltype == "fc":
            out_f = layer.get("out_features", 256)
            layers.append(nn.Linear(current_channels, out_f))
            current_channels = out_f
        elif ltype == "dropout":
            layers.append(nn.Dropout(layer.get("p", 0.5)))

    layers.append(nn.Linear(current_channels, num_classes))

    return nn.Sequential(*layers)
