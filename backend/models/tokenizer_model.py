import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class TokenizerModel(Base):
    __tablename__ = "tokenizers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(256))
    algorithm: Mapped[str] = mapped_column(
        Enum("bpe", "wordpiece", "unigram", "wordlevel", "char", name="tokenizer_algorithm"),
        default="bpe",
    )
    vocab_size: Mapped[int] = mapped_column(Integer, default=8192)
    actual_vocab_size: Mapped[int] = mapped_column(Integer, default=0)
    min_frequency: Mapped[int] = mapped_column(Integer, default=2)
    lowercase: Mapped[bool] = mapped_column(Boolean, default=False)
    byte_level: Mapped[bool] = mapped_column(Boolean, default=True)
    special_tokens: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("training", "ready", "error", name="tokenizer_status"),
        default="training",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
