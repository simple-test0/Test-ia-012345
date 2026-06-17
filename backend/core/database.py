from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Columns added after the initial schema. create_all() never ALTERs existing
# tables, so we add any missing ones here for seamless upgrades (SQLite).
_ADDED_COLUMNS = {
    "diffusion_models": [("total_bytes", "BIGINT DEFAULT 0")],
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
