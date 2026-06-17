from typing import Any, Dict

import torch
import torch.nn as nn


class PatchEmbedding(nn.Module):
    def __init__(self, image_size: int, patch_size: int, in_channels: int, dim: int):
        super().__init__()
        self.num_patches = (image_size // patch_size) ** 2
        self.proj = nn.Conv2d(in_channels, dim, kernel_size=patch_size, stride=patch_size)

    def forward(self, x):
        x = self.proj(x)
        return x.flatten(2).transpose(1, 2)


class ViT(nn.Module):
    def __init__(
        self,
        image_size: int,
        patch_size: int,
        num_classes: int,
        dim: int,
        depth: int,
        heads: int,
        mlp_dim: int,
        dropout: float,
        in_channels: int,
    ):
        super().__init__()
        num_patches = (image_size // patch_size) ** 2
        self.patch_emb = PatchEmbedding(image_size, patch_size, in_channels, dim)
        self.cls_token = nn.Parameter(torch.randn(1, 1, dim))
        self.pos_emb = nn.Parameter(torch.randn(1, num_patches + 1, dim))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=dim,
            nhead=heads,
            dim_feedforward=mlp_dim,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=depth)
        self.norm = nn.LayerNorm(dim)
        self.head = nn.Linear(dim, num_classes)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        B = x.shape[0]
        x = self.patch_emb(x)
        cls = self.cls_token.expand(B, -1, -1)
        x = torch.cat([cls, x], dim=1)
        x = self.dropout(x + self.pos_emb)
        x = self.transformer(x)
        x = self.norm(x[:, 0])
        return self.head(x)


def build_vit(config: Dict[str, Any]) -> nn.Module:
    return ViT(
        image_size=config.get("image_size", 224),
        patch_size=config.get("patch_size", 16),
        num_classes=config.get("num_classes", 10),
        dim=config.get("dim", 512),
        depth=config.get("depth", 6),
        heads=config.get("heads", 8),
        mlp_dim=config.get("mlp_dim", 1024),
        dropout=config.get("dropout", 0.1),
        in_channels=config.get("in_channels", 3),
    )
