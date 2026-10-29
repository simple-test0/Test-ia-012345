import asyncio
import logging
import random
import time
from typing import Dict, List, Optional

from api.websockets.manager import ws_manager
from core.config import utcnow
from services.image_gen.images import image_urls, latents_preview, save_images
from services.image_gen.pipeline_manager import apply_sampler, image_to_data_url, pipeline_manager

logger = logging.getLogger(__name__)

# At most this many preview frames per second go over the WebSocket.
_PREVIEW_MIN_INTERVAL = 0.25


class JobCancelled(Exception):
    pass


class GenerationWorker:
    """Runs queued generation jobs one at a time and reports progress."""

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: List[str] = []          # queued job ids, in order
        self._cancelled: set = set()
        self._current: Optional[str] = None
        self._progress: Dict[str, dict] = {}   # job id -> last step event

    # ── Queue API (used by the routes) ─────────────────────────────────────────

    def enqueue(self, job: dict) -> int:
        """Add a job without ever blocking. Raises asyncio.QueueFull."""
        self._queue.put_nowait(job)
        self._pending.append(job["id"])
        return len(self._pending)

    def position(self, job_id: str) -> Optional[int]:
        try:
            return self._pending.index(job_id) + 1
        except ValueError:
            return None

    def status(self, job_id: str) -> Optional[dict]:
        """Live status snapshot, sent to clients that (re)connect mid-job."""
        if job_id == self._current:
            return self._progress.get(job_id) or {"type": "started", "job_id": job_id}
        pos = self.position(job_id)
        if pos is not None:
            return {"type": "queued", "job_id": job_id, "position": pos}
        return None

    def cancel(self, job_id: str) -> Optional[str]:
        """Cancel a job. Returns "queued" (dropped from the queue right away),
        "running" (interrupted at the next step) or None (unknown/finished)."""
        if job_id == self._current:
            self._cancelled.add(job_id)
            return "running"
        if job_id in self._pending:
            self._pending.remove(job_id)
            self._cancelled.add(job_id)
            return "queued"
        return None

    async def broadcast_positions(self) -> None:
        for i, jid in enumerate(list(self._pending)):
            await ws_manager.send(jid, {"type": "queued", "job_id": jid, "position": i + 1})

    # ── Worker loop ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        logger.info("Generation worker started")
        while True:
            job = await self._queue.get()
            job_id = job.get("id")
            if job_id in self._pending:
                self._pending.remove(job_id)
            try:
                if job_id in self._cancelled:
                    continue  # cancelled while queued; the route already updated it
                await self.broadcast_positions()
                self._current = job_id
                await self._process(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Worker error on job {job_id}: {exc}")
            finally:
                self._current = None
                self._cancelled.discard(job_id)
                self._progress.pop(job_id, None)
                self._queue.task_done()

    async def _set_status(self, job_id: str, **fields) -> None:
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from models.image_job import ImageJob

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
            db_job = result.scalar_one_or_none()
            if db_job:
                for k, v in fields.items():
                    setattr(db_job, k, v)
                await db.commit()

    async def _process(self, job: dict) -> None:
        job_id = job["id"]
        await self._set_status(job_id, status="running")
        await ws_manager.send(job_id, {"type": "started", "job_id": job_id})

        start = time.monotonic()
        seed = job["seed"] if job.get("seed", -1) != -1 else random.randint(0, 2**32 - 1)
        loop = self._loop

        try:
            pipe = await pipeline_manager.get_pipeline(job["model_id"], job["repo_id"])
            # Everything below touches torch: keep it off the event loop.
            output_paths = await loop.run_in_executor(
                None, lambda: self._generate(pipe, job, seed)
            )
        except JobCancelled:
            await self._finish(job, "cancelled", [], None, start, seed)
            return
        except Exception as exc:
            logger.exception(f"Generation failed for job {job_id}")
            await self._finish(job, "failed", [], _friendly_error(exc), start, seed)
            return

        await self._finish(job, "completed", output_paths, None, start, seed)

    def _generate(self, pipe, job: dict, seed: int) -> List[str]:
        """Blocking generation (runs in a worker thread)."""
        import torch

        job_id = job["id"]
        total_steps = job["steps"]
        is_xl = "XL" in type(pipe).__name__
        last_preview = {"t": 0.0}

        if job.get("sampler"):
            apply_sampler(pipe, job["sampler"])

        lora = job.get("lora")
        lora_loaded = False
        if lora and hasattr(pipe, "load_lora_weights"):
            try:
                pipe.load_lora_weights(lora)
                lora_loaded = True
                logger.info(f"Loaded LoRA {lora}")
            except Exception as exc:
                logger.warning(f"Could not load LoRA {lora}: {exc}")
                self._send_threadsafe(job_id, {
                    "type": "warning",
                    "message": f"LoRA '{lora}' could not be loaded: {exc}",
                })

        def step_callback(pipeline, step_index, timestep, callback_kwargs):
            if job_id in self._cancelled:
                pipeline._interrupt = True  # diffusers stops at the next step
                return callback_kwargs
            step = step_index + 1
            now = time.monotonic()
            preview = None
            if step == total_steps or now - last_preview["t"] >= _PREVIEW_MIN_INTERVAL:
                last_preview["t"] = now
                img = latents_preview(callback_kwargs.get("latents"), is_xl)
                if img is not None:
                    preview = image_to_data_url(img, "JPEG")
            event = {
                "type": "step",
                "job_id": job_id,
                "step": step,
                "total_steps": total_steps,
                "preview": preview,
            }
            self._progress[job_id] = {**event, "preview": None}
            self._send_threadsafe(job_id, event)
            return callback_kwargs

        device = getattr(pipe, "_aistudio_device", "cpu")
        # MPS generators are poorly supported: seed on CPU (still reproducible).
        generator = torch.Generator(device="cuda" if device == "cuda" else "cpu")
        generator.manual_seed(seed)

        kwargs = dict(
            prompt=job["prompt"],
            num_inference_steps=total_steps,
            generator=generator,
            width=job["width"],
            height=job["height"],
            num_images_per_prompt=job.get("num_images", 1),
            callback_on_step_end=step_callback,
            callback_on_step_end_tensor_inputs=["latents"],
        )
        if job.get("negative_prompt"):
            kwargs["negative_prompt"] = job["negative_prompt"]
        if job.get("cfg_scale", 7.5) > 0:
            kwargs["guidance_scale"] = job["cfg_scale"]

        try:
            with torch.inference_mode():
                try:
                    result = pipe(**kwargs)
                except TypeError as exc:
                    # Pipelines without negative-prompt support (FLUX…).
                    if "negative_prompt" not in str(exc) or "negative_prompt" not in kwargs:
                        raise
                    kwargs.pop("negative_prompt")
                    result = pipe(**kwargs)
        finally:
            # Pipelines are cached/reused — remove the LoRA so it doesn't leak
            # into the next job.
            if lora_loaded:
                try:
                    pipe.unload_lora_weights()
                except Exception:
                    pass

        if job_id in self._cancelled:
            raise JobCancelled()
        return save_images(job_id, result.images)

    def _send_threadsafe(self, job_id: str, event: dict) -> None:
        asyncio.run_coroutine_threadsafe(ws_manager.send(job_id, event), self._loop)

    async def _finish(self, job, status, output_paths, error, start, seed) -> None:
        job_id = job["id"]
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        await self._set_status(
            job_id,
            status=status,
            output_paths=output_paths,
            error_message=error,
            duration_ms=duration_ms,
            completed_at=utcnow(),
            seed=seed,
        )
        if status == "completed":
            await ws_manager.send(job_id, {
                "type": "completed",
                "job_id": job_id,
                "images": image_urls(output_paths, thumbnail=True),
                "full_images": image_urls(output_paths, thumbnail=False),
                "duration_ms": duration_ms,
                "seed": seed,
            })
        elif status == "cancelled":
            await ws_manager.send(job_id, {"type": "cancelled", "job_id": job_id})
        else:
            await ws_manager.send(job_id, {"type": "error", "job_id": job_id, "message": error})


def _friendly_error(exc: Exception) -> str:
    msg = str(exc) or type(exc).__name__
    low = msg.lower()
    if "out of memory" in low or "outofmemory" in type(exc).__name__.lower():
        return (
            "Out of GPU memory — lower the resolution or the number of images, "
            "or pick a lighter model."
        )
    if "gated" in low or "401" in low or "403" in low:
        return (
            "This model is gated — set HUGGINGFACE_TOKEN in backend/.env and accept "
            "its license on huggingface.co."
        )
    if "no module named 'diffusers'" in low or "no module named 'torch'" in low:
        return "Image generation needs torch + diffusers: run `pip install -r requirements.txt`."
    return msg
