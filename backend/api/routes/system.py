import logging
import os
import threading
import time

from fastapi import APIRouter

from core.config import BASE_DIR
from core.logbuffer import log_buffer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

FRONTEND_PORT = 5173


@router.get("/logs")
async def get_logs(limit: int = 500):
    """Recent server logs (the Console page loads these before tailing the WS)."""
    return {"logs": log_buffer.tail(max(1, min(limit, 2000)))}


@router.post("/shutdown")
async def shutdown():
    """Stop the whole app: frontend, backend, and the start.bat supervisors.

    The supervisor loops in .run/ restart the servers after any exit, so a
    stop.flag is written first — they check it and exit instead of relooping.
    """
    logger.info("Arrêt de l'application demandé depuis l'interface")
    run_dir = BASE_DIR / ".run"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stop.flag").write_text("stop", encoding="utf-8")
    except Exception:
        logger.warning("Impossible d'écrire stop.flag", exc_info=True)

    threading.Thread(target=_shutdown_sequence, daemon=True).start()
    return {"status": "shutting_down"}


def _kill_frontend() -> None:
    """Terminate whatever is listening on the frontend port (Vite/Node)."""
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                conns = proc.net_connections(kind="tcp")
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
            for c in conns:
                if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == FRONTEND_PORT:
                    for child in proc.children(recursive=True):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    proc.terminate()
                    return
    except Exception:
        logger.warning("Impossible d'arrêter le serveur frontend", exc_info=True)


def _shutdown_sequence() -> None:
    # Belt-and-braces: never kill real processes from inside a test run.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    time.sleep(0.8)  # let the HTTP response reach the browser first
    _kill_frontend()

    # Under `uvicorn --reload`, this process is a child of the reloader —
    # exiting alone would just get restarted. Take the reloader down too.
    try:
        import psutil

        parent = psutil.Process(os.getpid()).parent()
        if parent and "python" in (parent.name() or "").lower():
            parent.terminate()
    except Exception:
        pass

    os._exit(0)
