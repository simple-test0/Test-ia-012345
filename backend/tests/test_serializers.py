"""Unit tests for the centralised serialisers (torch/PIL-free, run in light CI)."""
from datetime import UTC, datetime

from models.dataset import Dataset
from models.diffusion_model import DiffusionModel
from models.image_job import ImageJob
from models.training_run import TrainingRun
from schemas import (
    serialize_dataset,
    serialize_diffusion_model,
    serialize_image_job,
    serialize_run,
)


def test_serialize_diffusion_model_ready_is_full_progress():
    m = DiffusionModel(id="m1", name="SD", repo_id="org/sd", status="ready", min_vram_mb=4000)
    out = serialize_diffusion_model(m, vram_mb=8000)
    assert out["progress"] == 100
    assert out["compatible"] is True
    assert out["source"] == "downloaded"
    assert out["repo_id"] == "org/sd"


def test_serialize_diffusion_model_incompatible_when_vram_too_low():
    m = DiffusionModel(id="m2", name="SDXL", repo_id="org/sdxl", status="ready", min_vram_mb=12000)
    out = serialize_diffusion_model(m, vram_mb=4000)
    assert out["compatible"] is False


def test_serialize_image_job_list_trims_prompt():
    job = ImageJob(id="j1", status="completed", model_id="sd15", prompt="x" * 300)
    out = serialize_image_job(job, images=["data:img"], detail=False)
    assert len(out["prompt"]) == 100
    assert out["images"] == ["data:img"]
    assert "cfg_scale" not in out  # list view omits generation params


def test_serialize_image_job_detail_includes_params():
    job = ImageJob(id="j2", status="completed", model_id="sd15", prompt="hello", cfg_scale=7.5)
    out = serialize_image_job(job, images=[], detail=True)
    assert out["prompt"] == "hello"
    assert out["cfg_scale"] == 7.5
    assert "completed_at" in out


def test_serialize_run_exposes_started_at():
    started = datetime(2026, 1, 1, tzinfo=UTC)
    run = TrainingRun(id="r1", name="run", status="running", architecture="cnn", started_at=started)
    out = serialize_run(run)
    assert out["started_at"] == started.isoformat()
    assert out["status"] == "running"


def test_serialize_dataset_shape():
    ds = Dataset(id="d1", name="cifar", source="huggingface", task_type="classification")
    out = serialize_dataset(ds)
    assert out["id"] == "d1"
    assert out["task_type"] == "classification"
    assert out["created_at"] is None  # not flushed, server_default not applied
