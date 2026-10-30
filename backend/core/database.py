import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """WAL lets readers run while a background task writes (no "database is
    locked" when downloads/training/generation update rows concurrently)."""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        cur.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Columns added after the initial schema. create_all() never ALTERs existing
# tables, so we add any missing ones here for seamless upgrades (SQLite).
_ADDED_COLUMNS = {
    "diffusion_models": [("total_bytes", "BIGINT DEFAULT 0")],
    "image_jobs": [("init_image_path", "TEXT"), ("strength", "FLOAT")],
}


def _apply_lightweight_migrations(sync_conn) -> None:

    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row[1]
            for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns:
            if name not in existing:
                sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_lightweight_migrations)


async def recover_interrupted_work() -> None:
    """Fix rows left "in progress" by a previous crash or restart.

    Background work (generation queue, downloads, training subprocesses) lives
    in memory and does not survive a restart, so without this the UI would show
    jobs spinning forever.
    """
    from sqlalchemy import update

    from models.dataset import Dataset
    from models.diffusion_model import DiffusionModel
    from models.image_job import ImageJob
    from models.training_run import TrainingRun

    reason = "Interrupted by a server restart"
    async with AsyncSessionLocal() as db:
        results = [
            await db.execute(
                update(ImageJob)
                .where(ImageJob.status.in_(("queued", "running")))
                .values(status="failed", error_message=reason)
            ),
            await db.execute(
                update(TrainingRun)
                .where(TrainingRun.status.in_(("pending", "running", "paused")))
                .values(status="failed", error_message=reason)
            ),
            await db.execute(
                update(DiffusionModel)
                .where(DiffusionModel.status == "downloading")
                .values(status="error", error_message=reason + " — retry the download")
            ),
            await db.execute(
                update(Dataset)
                .where(Dataset.status == "downloading")
                .values(status="error", error_message=reason + " — retry the download")
            ),
        ]
        await db.commit()
    fixed = sum(r.rowcount or 0 for r in results)
    if fixed:
        logger.info(f"Marked {fixed} interrupted job(s)/download(s) as failed")


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
