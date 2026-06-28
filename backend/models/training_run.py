import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "paused", "completed", "failed", "cancelled", name="run_status"),
        default="pending",
    )
    architecture: Mapped[str] = mapped_column(String(64))
    arch_config: Mapped[dict] = mapped_column(JSON, default=dict)
    training_config: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hardware_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics_history: Mapped[list] = mapped_column(JSON, default=list)
    best_checkpoint_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_epoch: Mapped[int] = mapped_column(Integer, default=0)
    total_epochs: Mapped[int] = mapped_column(Integer, default=10)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
