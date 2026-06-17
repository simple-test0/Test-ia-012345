import uuid
from datetime import datetime
from typing import Optional

from core.database import Base
from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(Enum("huggingface", "kaggle", "upload", name="dataset_source"))
    source_identifier: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    task_type: Mapped[str] = mapped_column(
        Enum("classification", "detection", "segmentation", "generation", "nlp", name="task_type"),
        default="classification",
    )
    num_samples: Mapped[int] = mapped_column(Integer, default=0)
    num_classes: Mapped[int] = mapped_column(Integer, default=0)
    class_names: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(
        Enum("downloading", "ready", "error", name="dataset_status"),
        default="downloading",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
