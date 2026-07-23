import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import ensure_dirs, settings
from core.database import init_db

logging.basicConfig(level=logging.INFO)
# basicConfig is a no-op when the root logger already has handlers (pytest,
# embedding apps) — force the level so INFO reaches the Console buffer anyway.
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# In-memory log buffer feeding the Console page (REST backlog + WS tail).
# uvicorn's own loggers don't propagate to root, so attach to them explicitly.
from core.logbuffer import log_buffer  # noqa: E402

logging.getLogger().addHandler(log_buffer)
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _lg = logging.getLogger(_name)
    if log_buffer not in _lg.handlers:
        _lg.addHandler(log_buffer)


async def _recover_orphaned_jobs() -> None:
    """Fail records left in a transient state by a previous process.

    The generation queue, training subprocesses and download tasks are all
    in-memory, so none of them can resume after a restart — without this the
    corresponding rows would show as running/downloading forever.
    """
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from models.dataset import Dataset
    from models.diffusion_model import DiffusionModel
    from models.image_job import ImageJob
    from models.tokenizer_model import TokenizerModel
    from models.training_run import TrainingRun

    interrupted = "Interrompu par un redémarrage du serveur"
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ImageJob).where(ImageJob.status.in_(["queued", "running"]))
        )
        recovered = 0
        for job in result.scalars().all():
            job.status = "failed"
            job.error_message = interrupted
            recovered += 1

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

        result = await db.execute(
            select(DiffusionModel).where(DiffusionModel.status == "downloading")
        )
        for model in result.scalars().all():
            model.status = "error"
            model.error_message = interrupted
            recovered += 1

        if recovered:
            await db.commit()
            logger.info(f"Marked {recovered} orphaned record(s) as failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    log_buffer.set_loop(asyncio.get_running_loop())
    await init_db()
    await _recover_orphaned_jobs()

    # CLAUDE: add new agent tools here — import triggers @register_tool
    import services.agent.tools.calculator  # noqa: F401
    import services.agent.tools.code_executor  # noqa: F401
    import services.agent.tools.web_search  # noqa: F401

    # Generation queue + worker
    from services.image_gen.worker import GenerationWorker
    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
    worker = GenerationWorker(queue)
    worker_task = asyncio.create_task(worker.run())
    app.state.generation_queue = queue

    logger.info("AI Studio backend started")
    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    from services.image_gen.pipeline_manager import pipeline_manager
    await pipeline_manager.unload_all()
    logger.info("AI Studio backend stopped")


app = FastAPI(
    title="AI Studio",
    description="Local AI application — Image Generation, Agents, Labs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes — CLAUDE: add new routers here with include_router
from fastapi import Depends  # noqa: E402

from api.routes import agent, hardware, image_gen, labs, system  # noqa: E402
from core.security import require_api_token  # noqa: E402

_auth = [Depends(require_api_token)]
app.include_router(hardware.router, prefix="/api/v1", dependencies=_auth)
app.include_router(image_gen.router, prefix="/api/v1", dependencies=_auth)
app.include_router(agent.router, prefix="/api/v1", dependencies=_auth)
app.include_router(labs.router, prefix="/api/v1", dependencies=_auth)
app.include_router(system.router, prefix="/api/v1", dependencies=_auth)

# WebSocket routes
from api.websockets.agent_ws import ws_router as agent_ws  # noqa: E402
from api.websockets.image_ws import ws_router as image_ws  # noqa: E402
from api.websockets.logs_ws import ws_router as logs_ws  # noqa: E402
from api.websockets.training_ws import ws_router as training_ws  # noqa: E402

app.include_router(image_ws)
app.include_router(agent_ws)
app.include_router(training_ws)
app.include_router(logs_ws)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
