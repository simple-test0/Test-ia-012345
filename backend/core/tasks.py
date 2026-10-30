"""Fire-and-forget background tasks that are neither garbage-collected
mid-flight (asyncio only keeps weak references) nor fail silently."""
import asyncio
import logging
import threading
from typing import Coroutine, Set

logger = logging.getLogger(__name__)

_tasks: Set[asyncio.Task] = set()
_detached_running = 0
_detached_lock = threading.Lock()


def detached_running() -> int:
    """Number of detached jobs (downloads, model loads, generations) in flight."""
    return _detached_running


def spawn(coro: Coroutine, name: str = "") -> asyncio.Task:
    task = asyncio.create_task(coro, name=name or None)
    _tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error(f"Background task {t.get_name()} failed", exc_info=t.exception())

    task.add_done_callback(_done)
    return task


def run_detached(fn, *args, **kwargs) -> "asyncio.Future":
    """Run a long blocking call (model download/load, generation) in a daemon
    thread and await its result.

    Unlike asyncio.to_thread, the process never waits for these threads on
    shutdown: Ctrl+C stops the app immediately even mid-download.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def _set(setter, value) -> None:
        if not future.done():
            setter(value)

    def _deliver(setter, value) -> None:
        try:
            loop.call_soon_threadsafe(_set, setter, value)
        except RuntimeError:
            pass  # event loop already closed (app shutting down)

    def _worker() -> None:
        global _detached_running
        with _detached_lock:
            _detached_running += 1
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # forwarded to the awaiting task
            _deliver(future.set_exception, exc)
        else:
            _deliver(future.set_result, result)
        finally:
            with _detached_lock:
                _detached_running -= 1

    threading.Thread(target=_worker, name=f"detached-{getattr(fn, '__name__', 'job')}",
                     daemon=True).start()
    return future
