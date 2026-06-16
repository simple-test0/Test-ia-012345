import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import ensure_dirs, settings
from core.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    await init_db()

    # Import tools so they self-register
    import services.agent.tools.web_search  # noqa: F401
    import services.agent.tools.calculator  # noqa: F401
    import services.agent.tools.code_executor  # noqa: F401

    # Generation queue + worker
    from services.image_gen.worker import GenerationWorker
    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
    worker = GenerationWorker(queue)
    worker_task = asyncio.create_task(worker.run())

    def _log_worker_exit(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Generation worker exited unexpectedly: %s", exc, exc_info=exc)

    worker_task.add_done_callback(_log_worker_exit)
    app.state.generation_queue = queue

    # Log the detected accelerator once at startup for easier diagnostics.
    try:
        from hardware.detector import detect_hardware

        hw = detect_hardware()
        logger.info(
            "Accelerator: %s | GPUs: %s | RAM: %d MB",
            hw.accelerator_backend,
            [g.name for g in hw.gpus] or "none",
            hw.ram_total_mb,
        )
    except Exception:
        logger.warning("Hardware detection failed at startup", exc_info=True)

    logger.info("AI Studio backend started")
    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    from services.image_gen.pipeline_manager import pipeline_manager
    await pipeline_manager.unload_all()

    from services.agent.ollama_client import ollama_client
    await ollama_client.aclose()
    logger.info("AI Studio backend stopped")


app = FastAPI(
    title="AI Studio",
    description="Local AI application — Image Generation, Agents, Labs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
from api.routes import hardware, image_gen, agent, labs  # noqa: E402

app.include_router(hardware.router, prefix="/api/v1")
app.include_router(image_gen.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(labs.router, prefix="/api/v1")

# WebSocket routes
from api.websockets.image_ws import ws_router as image_ws  # noqa: E402
from api.websockets.agent_ws import ws_router as agent_ws  # noqa: E402
from api.websockets.training_ws import ws_router as training_ws  # noqa: E402

app.include_router(image_ws)
app.include_router(agent_ws)
app.include_router(training_ws)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
