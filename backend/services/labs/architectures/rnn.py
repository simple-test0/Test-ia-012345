from typing import Any, Dict

import torch.nn as nn


class RNNClassifier(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        embed_dim: int,
        hidden_size: int,
        num_layers: int,
        num_classes: int,
        dropout: float,
        bidirectional: bool,
        rnn_type: str,
    ):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        rnn_cls = {"rnn": nn.RNN, "lstm": nn.LSTM, "gru": nn.GRU}[rnn_type]
        self.rnn = rnn_cls(
            embed_dim,
            hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
            bidirectional=bidirectional,
        )
        factor = 2 if bidirectional else 1
        self.head = nn.Linear(hidden_size * factor, num_classes)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        emb = self.dropout(self.embedding(x))
        out, _ = self.rnn(emb)
        last = out[:, -1, :]
        return self.head(self.dropout(last))


def build_rnn(config: Dict[str, Any]) -> nn.Module:
    return RNNClassifier(
        vocab_size=config.get("vocab_size", 10000),
        embed_dim=config.get("embed_dim", 128),
        hidden_size=config.get("hidden_size", 256),
        num_layers=config.get("num_layers", 2),
        num_classes=config.get("num_classes", 10),
        dropout=config.get("dropout", 0.3),
        bidirectional=config.get("bidirectional", False),
        rnn_type="rnn",
    )


def build_lstm(config: Dict[str, Any]) -> nn.Module:
    return RNNClassifier(
        vocab_size=config.get("vocab_size", 10000),
        embed_dim=config.get("embed_dim", 128),
        hidden_size=config.get("hidden_size", 256),
        num_layers=config.get("num_layers", 2),
        num_classes=config.get("num_classes", 10),
        dropout=config.get("dropout", 0.3),
        bidirectional=config.get("bidirectional", True),
        rnn_type="lstm",
    )


def build_gru(config: Dict[str, Any]) -> nn.Module:
    return RNNClassifier(
        vocab_size=config.get("vocab_size", 10000),
        embed_dim=config.get("embed_dim", 128),
        hidden_size=config.get("hidden_size", 256),
        num_layers=config.get("num_layers", 2),
        num_classes=config.get("num_classes", 10),
        dropout=config.get("dropout", 0.3),
        bidirectional=config.get("bidirectional", True),
        rnn_type="gru",
    )
