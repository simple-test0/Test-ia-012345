import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DiffusionModel(Base):
    __tablename__ = "diffusion_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(256))
    repo_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    pipeline_class: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("downloading", "ready", "error", name="diffusion_model_status"),
        default="downloading",
    )
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    min_vram_mb: Mapped[int] = mapped_column(Integer, default=0)
    recommended_steps: Mapped[int] = mapped_column(Integer, default=25)
    default_cfg: Mapped[float] = mapped_column(Float, default=7.5)
    default_width: Mapped[int] = mapped_column(Integer, default=512)
    default_height: Mapped[int] = mapped_column(Integer, default=512)
    supports_negative_prompt: Mapped[bool] = mapped_column(Boolean, default=True)

    gated: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    downloads: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
