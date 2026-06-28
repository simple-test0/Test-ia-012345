import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ImageJob(Base):
    __tablename__ = "image_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(
        Enum("queued", "running", "completed", "failed", "cancelled", name="job_status"),
        default="queued",
    )
    model_id: Mapped[str] = mapped_column(String(256))
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int] = mapped_column(Integer, default=512)
    height: Mapped[int] = mapped_column(Integer, default=512)
    steps: Mapped[int] = mapped_column(Integer, default=20)
    cfg_scale: Mapped[float] = mapped_column(default=7.5)
    seed: Mapped[int] = mapped_column(Integer, default=-1)
    sampler: Mapped[str] = mapped_column(String(64), default="DPM++ 2M")
    num_images: Mapped[int] = mapped_column(Integer, default=1)
    output_paths: Mapped[list | None] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
