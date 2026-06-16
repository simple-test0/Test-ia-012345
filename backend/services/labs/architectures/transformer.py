import math
from typing import Any, Dict

import torch
import torch.nn as nn


class TransformerLanguageModel(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        n_embd: int,
        n_head: int,
        n_layer: int,
        max_seq_len: int,
        dropout: float,
        num_classes: int = 0,
    ):
        super().__init__()
        self.token_emb = nn.Embedding(vocab_size, n_embd)
        self.pos_emb = nn.Embedding(max_seq_len, n_embd)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=n_embd,
            nhead=n_head,
            dim_feedforward=n_embd * 4,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layer)
        self.norm = nn.LayerNorm(n_embd)
        if num_classes > 0:
            self.head = nn.Linear(n_embd, num_classes)
        else:
            self.head = nn.Linear(n_embd, vocab_size)
        self.dropout = nn.Dropout(dropout)
        self.max_seq_len = max_seq_len

    def forward(self, x):
        B, T = x.shape
        positions = torch.arange(T, device=x.device).unsqueeze(0)
        emb = self.dropout(self.token_emb(x) + self.pos_emb(positions))
        out = self.transformer(emb)
        out = self.norm(out)
        return self.head(out[:, -1, :])


def build_transformer(config: Dict[str, Any]) -> nn.Module:
    return TransformerLanguageModel(
        vocab_size=config.get("vocab_size", 50257),
        n_embd=config.get("n_embd", 256),
        n_head=config.get("n_head", 8),
        n_layer=config.get("n_layer", 6),
        max_seq_len=config.get("max_seq_len", 512),
        dropout=config.get("dropout", 0.1),
        num_classes=config.get("num_classes", 0),
    )
