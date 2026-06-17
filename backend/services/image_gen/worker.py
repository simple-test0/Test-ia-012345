import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Optional

from api.websockets.manager import ws_manager
from core.config import settings

from services.image_gen.model_registry import get_model
from services.image_gen.pipeline_manager import apply_sampler, image_to_base64, pipeline_manager

logger = logging.getLogger(__name__)


class GenerationWorker:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def run(self) -> None:
        self._loop = asyncio.get_event_loop()
        logger.info("Generation worker started")
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Worker error on job {job.get('id')}: {exc}")
            finally:
                self._queue.task_done()

    async def _process(self, job: dict) -> None:
        job_id = job["id"]
        model_id = job["model_id"]
        repo_id = job["repo_id"]

        await ws_manager.send(job_id, {"type": "started", "job_id": job_id})

        # DB update — import here to avoid circular at module load
        from core.database import AsyncSessionLocal
        from models.image_job import ImageJob
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
            db_job = result.scalar_one_or_none()
            if db_job:
                db_job.status = "running"
                await db.commit()

        start_ms = int(time.time() * 1000)
        output_paths = []
        error_msg = None

        try:
            pipe = await pipeline_manager.get_pipeline(model_id, repo_id)
            spec = get_model(model_id)
            apply_sampler(pipe, job.get("sampler", ""), spec.family if spec else "")
            loop = self._loop
            step_data = {"current": 0}

            # Live previews are expensive (a VAE decode per shown step). Skip them
            # entirely on CPU and throttle to a handful per run elsewhere so small
            # configs stay responsive.
            from hardware.detector import detect_hardware
            backend = detect_hardware().accelerator_backend
            total_steps = max(1, int(job["steps"]))
            preview_enabled = settings.enable_live_preview and backend != "cpu"
            preview_interval = max(1, total_steps // 8)

            def step_callback(pipeline, step_index, timestep, callback_kwargs):
                step_data["current"] = step_index + 1
                latents = callback_kwargs.get("latents")
                preview_b64 = None

                show_preview = (
                    preview_enabled
                    and latents is not None
                    and (step_index % preview_interval == 0 or step_data["current"] >= total_steps)
                )
                if show_preview:
                    try:
                        import torch
                        with torch.no_grad():
                            decoded = pipeline.vae.decode(
                                latents / pipeline.vae.config.scaling_factor, return_dict=False
                            )[0]
                            decoded = (decoded / 2 + 0.5).clamp(0, 1)
                            decoded = decoded.cpu().permute(0, 2, 3, 1).float().numpy()
                            import numpy as np
                            from PIL import Image
                            img = Image.fromarray((decoded[0] * 255).astype(np.uint8))
                            img.thumbnail((256, 256))
                            preview_b64 = image_to_base64(img)
                    except Exception:
                        logger.debug("Live preview decode failed at step %d", step_index, exc_info=True)

                asyncio.run_coroutine_threadsafe(
                    ws_manager.send(job_id, {
                        "type": "step",
                        "step": step_data["current"],
                        "total": job["steps"],
                        "preview": preview_b64,
                    }),
                    loop,
                )
                return callback_kwargs

            seed = job["seed"]
            if seed == -1:
                seed = random.randint(0, 2**32 - 1)

            import torch
            # A CPU generator is portable across CUDA/ROCm/XPU/MPS/CPU and keeps
            # seeds reproducible even when components are offloaded between devices.
            generator = torch.Generator(device="cpu")
            generator.manual_seed(seed)

            generate_kwargs = dict(
                prompt=job["prompt"],
                num_inference_steps=job["steps"],
                generator=generator,
                width=job["width"],
                height=job["height"],
                num_images_per_prompt=job.get("num_images", 1),
                callback_on_step_end=step_callback,
                callback_on_step_end_tensor_inputs=["latents"],
            )
            if job.get("negative_prompt"):
                generate_kwargs["negative_prompt"] = job["negative_prompt"]
            if job.get("cfg_scale", 7.5) > 0:
                generate_kwargs["guidance_scale"] = job["cfg_scale"]

            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: pipe(**generate_kwargs)
            )
            images = result.images

            settings.images_dir.mkdir(parents=True, exist_ok=True)
            for i, img in enumerate(images):
                fname = f"{job_id}_{i}.png"
                fpath = settings.images_dir / fname
                img.save(str(fpath))
                output_paths.append(str(fpath))

        except Exception as exc:
            error_msg = str(exc)
            logger.exception(f"Generation failed for job {job_id}")

        duration_ms = int(time.time() * 1000) - start_ms
        status = "completed" if not error_msg else "failed"

        # Produce base64 previews of final images
        image_b64s = []
        for p in output_paths:
            try:
                from PIL import Image as PILImage
                img = PILImage.open(p)
                image_b64s.append(image_to_base64(img, "PNG"))
            except Exception:
                logger.warning("Could not encode result image %s", p, exc_info=True)
                image_b64s.append(None)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ImageJob).where(ImageJob.id == job_id))
            db_job = result.scalar_one_or_none()
            if db_job:
                db_job.status = status
                db_job.output_paths = output_paths
                db_job.error_message = error_msg
                db_job.duration_ms = duration_ms
                db_job.completed_at = datetime.utcnow()
                await db.commit()

        if error_msg:
            await ws_manager.send(job_id, {"type": "error", "message": error_msg})
        else:
            await ws_manager.send(job_id, {
                "type": "completed",
                "job_id": job_id,
                "image_paths": output_paths,
                "images_b64": image_b64s,
                "duration_ms": duration_ms,
                "seed": seed,
            })
