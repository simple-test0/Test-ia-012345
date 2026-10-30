import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from core.config import ensure_dirs, settings
from core.database import init_db, recover_interrupted_work

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_VERSION = "1.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    await init_db()
    await recover_interrupted_work()

    # Import tools so they self-register
    import services.agent.tools.calculator  # noqa: F401
    import services.agent.tools.code_executor  # noqa: F401
    import services.agent.tools.web_search  # noqa: F401

    # Warm the hardware cache off the event loop: the first detection imports
    # torch, which can take several seconds and would otherwise stall the
    # first request.
    from hardware.detector import detect_hardware_cached

    loop = asyncio.get_running_loop()
    warmup = loop.run_in_executor(None, detect_hardware_cached)

    # Generation queue + worker
    from services.image_gen.worker import GenerationWorker
    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
    worker = GenerationWorker(queue)
    worker_task = asyncio.create_task(worker.run())
    app.state.generation_queue = queue
    app.state.generation_worker = worker

    logger.info("AI Studio backend started")
    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    from services.labs.trainer import training_manager
    await loop.run_in_executor(None, training_manager.stop_all)

    from services.image_gen.pipeline_manager import pipeline_manager
    await pipeline_manager.unload_all()
    try:
        await asyncio.wait_for(warmup, timeout=1)
    except Exception:
        pass
    logger.info("AI Studio backend stopped")

    from core.tasks import detached_running

    if settings.fast_shutdown and detached_running():
        # Hugging Face downloads use their own thread pool, which Python would
        # wait for before exiting (minutes for a large model). Nothing left
        # needs saving at this point, so leave right away.
        logger.info("Interrupting in-progress downloads/generation and exiting now")
        logging.shutdown()
        os._exit(0)


app = FastAPI(
    title="AI Studio",
    description="Local AI application — Image Generation, Agents, Labs",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# JSON lists (jobs, runs, metrics) compress very well.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# REST routes
from api.routes import agent, hardware, image_gen, labs  # noqa: E402
from core.security import require_api_token  # noqa: E402

_auth = [Depends(require_api_token)]
app.include_router(hardware.router, prefix="/api/v1", dependencies=_auth)
app.include_router(image_gen.router, prefix="/api/v1", dependencies=_auth)
app.include_router(image_gen.files_router, prefix="/api/v1")  # header or ?token=
app.include_router(agent.router, prefix="/api/v1", dependencies=_auth)
app.include_router(labs.router, prefix="/api/v1", dependencies=_auth)

# WebSocket routes
from api.websockets.agent_ws import ws_router as agent_ws  # noqa: E402
from api.websockets.image_ws import ws_router as image_ws  # noqa: E402
from api.websockets.training_ws import ws_router as training_ws  # noqa: E402

app.include_router(image_ws)
app.include_router(agent_ws)
app.include_router(training_ws)


@app.get("/health")
@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


# ── Built UI (MODE=prod / single-port) ────────────────────────────────────────
# When frontend/dist exists, the backend serves it too: one URL, no Node needed
# at runtime. In dev, Vite serves the UI instead and this is skipped.
from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core.config import BASE_DIR  # noqa: E402

_DIST = BASE_DIR / "frontend" / "dist"
if settings.serve_frontend and (_DIST / "index.html").is_file():
    if (_DIST / "assets").is_dir():
        # Hashed file names: safe to cache forever.
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404)
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_DIST.resolve()):
            return FileResponse(candidate)
        # Client-side routes (/image, /agent…) all load the app shell.
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})
