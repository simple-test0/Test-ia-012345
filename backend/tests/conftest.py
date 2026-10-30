import os
import tempfile

# Isolate tests from the user's real data (DB, images, models): settings are
# read at import time, so this must run before any app module is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aistudio-tests-")
os.environ.setdefault("SERVE_FRONTEND", "false")
os.environ["FAST_SHUTDOWN"] = "false"  # os._exit would end the test run

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import models  # noqa: F401  (registers all tables on Base.metadata)
from core.database import Base


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """An in-memory SQLite AsyncSession with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()
