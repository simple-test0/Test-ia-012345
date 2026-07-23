"""AI Studio Labs — standalone training app.

Reuses the backend's labs services (architectures, datasets, tokenizers,
training subprocesses) but runs as an independent app:
- its own SQLite database (data/db/labs.db), created automatically at startup
- its own port (8100) and its own zero-build static UI (labs-app/static)
- the backend virtualenv, so no dependency is installed twice
"""
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT / "backend"))

# Own database, before core.config is imported. Data folders (datasets,
# models, tokenizers) stay shared with the main app on purpose: a dataset
# downloaded in one is usable in the other; only the records DB is separate.
os.environ.setdefault("DB_PATH", str(ROOT / "data" / "db" / "labs.db"))

import asyncio  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core.config import ensure_dirs  # noqa: E402
from core.database import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("labs")

from core.logbuffer import log_buffer  # noqa: E402

logging.getLogger().addHandler(log_buffer)
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _lg = logging.getLogger(_name)
    if log_buffer not in _lg.handlers:
        _lg.addHandler(log_buffer)


async def _recover_orphaned_records() -> None:
    """Mark records left in a transient state by a previous process as failed."""
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from models.dataset import Dataset
    from models.tokenizer_model import TokenizerModel
    from models.training_run import TrainingRun

    interrupted = "Interrompu par un redémarrage du serveur"
    async with AsyncSessionLocal() as db:
        recovered = 0
        result = await db.execute(
            select(TrainingRun).where(TrainingRun.status.in_(["pending", "running", "paused"]))
        )
        for run in result.scalars().all():
            run.status = "failed"
            run.error_message = interrupted
            recovered += 1

        result = await db.execute(select(Dataset).where(Dataset.status == "downloading"))
        for ds in result.scalars().all():
            ds.status = "error"
            ds.error_message = interrupted
            recovered += 1

        result = await db.execute(
            select(TokenizerModel).where(TokenizerModel.status == "training")
        )
        for tok in result.scalars().all():
            tok.status = "error"
            tok.error_message = interrupted
            recovered += 1

        if recovered:
            await db.commit()
            logger.info(f"Marked {recovered} orphaned record(s) as failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    log_buffer.set_loop(asyncio.get_running_loop())
    await init_db()
    await _recover_orphaned_records()
    logger.info("Labs standalone app started")
    yield
    logger.info("Labs standalone app stopped")


app = FastAPI(
    title="AI Studio — Labs",
    description="Application autonome d'entraînement de réseaux de neurones",
    version="1.0.0",
    lifespan=lifespan,
)

from api.routes import hardware, labs  # noqa: E402
from core.security import require_api_token  # noqa: E402

_auth = [Depends(require_api_token)]
app.include_router(labs.router, prefix="/api/v1", dependencies=_auth)
app.include_router(hardware.router, prefix="/api/v1", dependencies=_auth)

from api.websockets.logs_ws import ws_router as logs_ws  # noqa: E402
from api.websockets.training_ws import ws_router as training_ws  # noqa: E402

app.include_router(training_ws)
app.include_router(logs_ws)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "labs", "version": "1.0.0"}


@app.get("/api/v1/system/logs")
async def get_logs(limit: int = 500):
    return {"logs": log_buffer.tail(max(1, min(limit, 2000)))}


@app.post("/api/v1/system/shutdown")
async def shutdown():
    """Stop the labs app (and its start-labs.bat supervisor loop)."""
    logger.info("Arrêt de Labs demandé depuis l'interface")
    run_dir = ROOT / ".run"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "labs-stop.flag").write_text("stop", encoding="utf-8")
    except Exception:
        logger.warning("Impossible d'écrire labs-stop.flag", exc_info=True)

    def _exit() -> None:
        if "PYTEST_CURRENT_TEST" in os.environ:
            return
        time.sleep(0.8)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"status": "shutting_down"}


# Mounted last: API and WS routes above take precedence over static files.
app.mount("/", StaticFiles(directory=str(APP_DIR / "static"), html=True), name="static")
