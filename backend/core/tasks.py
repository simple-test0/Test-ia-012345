"""Fire-and-forget background tasks that are neither garbage-collected
mid-flight (asyncio only keeps weak references) nor fail silently."""
import asyncio
import logging
from typing import Coroutine, Set

logger = logging.getLogger(__name__)

_tasks: Set[asyncio.Task] = set()


def spawn(coro: Coroutine, name: str = "") -> asyncio.Task:
    task = asyncio.create_task(coro, name=name or None)
    _tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error(f"Background task {t.get_name()} failed", exc_info=t.exception())

    task.add_done_callback(_done)
    return task
