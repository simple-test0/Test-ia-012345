"""Integration tests hitting every router via FastAPI TestClient.

torch is importable in CI's heavy env but diffusers is not; the image worker
fails gracefully in the background, which is fine — we only assert the HTTP
contract here. Network-dependent calls (HF search, Ollama) are mocked/handled.
"""
import importlib.util

import pytest

# TestClient drives the lifespan, which imports the worker + pipeline manager.
# Those import torch lazily/at module load, so skip the whole module without it.
_HAS_TORCH = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not _HAS_TORCH, reason="torch not installed")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app
    from services.image_gen.pipeline_manager import pipeline_manager

    async def no_model(model_id, repo_id):
        # Never download multi-GB weights from the test suite.
        raise RuntimeError("model loading disabled in tests")

    original = pipeline_manager.get_pipeline
    pipeline_manager.get_pipeline = no_model
    try:
        with TestClient(app) as c:
            yield c
    finally:
        pipeline_manager.get_pipeline = original


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_hardware_info(client):
    r = client.get("/api/v1/hardware/info")
    assert r.status_code == 200
    body = r.json()
    assert "ram_total_mb" in body and "gpus" in body


def test_hardware_recommendations(client):
    r = client.get("/api/v1/hardware/recommendations")
    assert r.status_code == 200
    assert "image_gen" in r.json() and "training" in r.json()


def test_image_models_curated_first(client):
    r = client.get("/api/v1/image/models")
    assert r.status_code == 200
    models = r.json()
    assert len(models) >= 6
    assert models[0]["recommended"] is True
    assert models[0]["source"] == "curated"


def test_generate_unknown_model_404(client):
    r = client.post("/api/v1/image/generate", json={"model_id": "nope", "prompt": "x"})
    assert r.status_code == 404


def test_generate_queues_job_and_lists(client):
    r = client.post(
        "/api/v1/image/generate",
        json={"model_id": "sd15", "prompt": "a cat", "steps": 1},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    jobs = client.get("/api/v1/image/jobs").json()
    assert isinstance(jobs, list)
    assert all("job_id" in j and "images" in j for j in jobs)


def test_hf_search_mocked(client, monkeypatch):
    import api.routes.image_gen as route

    monkeypatch.setattr(
        route, "search_hf_models",
        lambda q, limit=25: [{"repo_id": "org/m", "name": "m", "downloads": 1,
                              "likes": 2, "gated": False, "pipeline_tag": "text-to-image",
                              "tags": []}],
    )
    r = client.get("/api/v1/image/hf/search", params={"query": "sdxl"})
    assert r.status_code == 200
    assert r.json()["results"][0]["repo_id"] == "org/m"


def test_hf_search_empty_query(client):
    r = client.get("/api/v1/image/hf/search", params={"query": "  "})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_hf_model_status_404(client):
    assert client.get("/api/v1/image/hf/models/nonexistent").status_code == 404


def test_agent_tools_registered(client):
    r = client.get("/api/v1/agent/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert {"web_search", "calculator", "code_executor"} <= names


def test_agent_models_handles_offline_ollama(client):
    r = client.get("/api/v1/agent/models")
    assert r.status_code == 200
    assert "available" in r.json()


def test_agent_session_crud(client):
    created = client.post("/api/v1/agent/sessions", json={"name": "t"}).json()
    sid = created["id"]
    got = client.get(f"/api/v1/agent/sessions/{sid}")
    assert got.status_code == 200
    assert client.delete(f"/api/v1/agent/sessions/{sid}").status_code == 200
    assert client.get(f"/api/v1/agent/sessions/{sid}").status_code == 404


def test_labs_architectures(client):
    r = client.get("/api/v1/labs/architectures")
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()}
    assert "cnn" in ids


def test_labs_lists(client):
    assert client.get("/api/v1/labs/datasets").status_code == 200
    assert client.get("/api/v1/labs/runs").status_code == 200


def test_agent_session_update_and_summary(client):
    created = client.post("/api/v1/agent/sessions", json={"name": "s"}).json()
    assert created["message_count"] == 0
    r = client.patch(
        f"/api/v1/agent/sessions/{created['id']}", json={"system_prompt": "Be brief."}
    )
    assert r.status_code == 200
    got = client.get(f"/api/v1/agent/sessions/{created['id']}").json()
    assert got["system_prompt"] == "Be brief."
    client.delete(f"/api/v1/agent/sessions/{created['id']}")


def test_image_job_lifecycle(client):
    import time

    r = client.post("/api/v1/image/generate", json={"model_id": "sd15", "prompt": "x", "steps": 1})
    job_id = r.json()["job_id"]
    # Without diffusers (CI) the worker fails fast; with it, cancel instead.
    client.post(f"/api/v1/image/jobs/{job_id}/cancel")
    deadline = time.time() + 30
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/v1/image/jobs/{job_id}").json()["status"]
        if status in ("failed", "cancelled", "completed"):
            break
        time.sleep(0.2)
    assert status in ("failed", "cancelled", "completed")
    assert client.get("/api/v1/image/jobs/count").json()["total"] >= 1
    assert client.delete(f"/api/v1/image/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/v1/image/jobs/{job_id}").status_code == 404


def test_image_file_route_rejects_bad_names(client):
    assert client.get("/api/v1/image/files/..%2Fapp.db").status_code == 404
    missing = "0f8fad5b-d9cb-469f-a165-70867728950e_0.png"
    assert client.get(f"/api/v1/image/files/{missing}").status_code == 404


def test_generate_validation(client):
    r = client.post("/api/v1/image/generate", json={"model_id": "sd15", "prompt": "   "})
    assert r.status_code == 422


def test_dataset_upload_and_delete(client):
    files = [
        ("files", ("../evil.txt", b"hello", "text/plain")),
        ("files", ("b.csv", b"a,b\n1,2\n", "text/csv")),
    ]
    r = client.post("/api/v1/labs/datasets/upload", data={"name": "up"}, files=files)
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["status"] == "ready" and ds["num_samples"] == 2 and ds["size_bytes"] == 13
    from pathlib import Path

    assert (Path(ds["local_path"]) / "evil.txt").exists()
    assert client.delete(f"/api/v1/labs/datasets/{ds['id']}").status_code == 200
    assert not Path(ds["local_path"]).exists()


def test_training_run_end_to_end(client):
    """Real subprocess (spawn) on CPU: 1 tiny epoch on random data."""
    import time

    r = client.post("/api/v1/labs/runs", json={
        "name": "t", "architecture": "cnn",
        "arch_config": {"num_classes": 2, "in_channels": 1, "image_size": 8},
        "training_config": {"epochs": 1, "batch_size": 64},
    })
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    deadline = time.time() + 120
    run = {}
    while time.time() < deadline:
        run = client.get(f"/api/v1/labs/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert run["status"] == "completed", run.get("error_message")
    assert run["current_epoch"] == 1 and run["metrics_history"]
    r = client.post(f"/api/v1/labs/runs/{run_id}/export", json={"format": "safetensors"})
    if r.status_code == 200:  # needs the safetensors package
        d = client.get(f"/api/v1/labs/runs/{run_id}/export/download")
        assert d.status_code == 200 and len(d.content) > 0
    assert client.delete(f"/api/v1/labs/runs/{run_id}").status_code == 200


def test_run_validation(client):
    r = client.post("/api/v1/labs/runs", json={
        "name": "bad", "architecture": "cnn", "training_config": {"epochs": 0},
    })
    assert r.status_code == 422


def _png_data_url(w: int, h: int) -> str:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_img2img_request_fits_source_aspect(client):
    r = client.post("/api/v1/image/generate", json={
        "model_id": "sd15", "prompt": "x", "steps": 1, "width": 512, "height": 512,
        "init_image": _png_data_url(1000, 500), "strength": 0.5,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["width"], body["height"]) == (512, 256)  # 2:1 kept, multiples of 8
    assert body["init_image"].endswith(f"{body['job_id']}.png")
    img = client.get(body["init_image"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    job = client.get(f"/api/v1/image/jobs/{body['job_id']}").json()
    assert job["strength"] == 0.5 and job["init_image"]
    client.post(f"/api/v1/image/jobs/{body['job_id']}/cancel")
    assert client.delete(f"/api/v1/image/jobs/{body['job_id']}").status_code == 200
    assert client.get(body["init_image"]).status_code == 404  # source deleted too


def test_img2img_rejects_garbage(client):
    r = client.post("/api/v1/image/generate", json={
        "model_id": "sd15", "prompt": "x", "init_image": "data:image/png;base64,bm90IGFuIGltYWdl",
    })
    assert r.status_code == 422
    assert client.get("/api/v1/image/files/init/not-a-uuid.png").status_code == 404


def test_agent_stop_keeps_partial_answer(client, monkeypatch):
    import asyncio

    from services.agent.ollama_client import OllamaClient

    async def slow_chat(self, model, messages, tools=None, on_token=None, **kw):
        for i in range(200):
            await on_token(f"w{i} ")
            await asyncio.sleep(0.02)
        return {"content": "never", "tool_calls": []}

    monkeypatch.setattr(OllamaClient, "chat", slow_chat)
    sid = client.post("/api/v1/agent/sessions", json={"name": "s", "model_id": "m"}).json()["id"]
    with client.websocket_connect(f"/ws/agent/{sid}") as ws:
        ws.send_json({"content": "hello", "model_id": "m"})
        assert ws.receive_json()["type"] == "token"
        ws.send_json({"content": "second while busy", "model_id": "m"})
        seen_busy = False
        ws.send_json({"type": "stop"})
        while True:
            evt = ws.receive_json()
            if evt["type"] == "error" and "already" in evt["message"]:
                seen_busy = True
            if evt["type"] == "message_complete":
                break
        assert evt["stopped"] is True and "[interrompu]" in evt["full_content"]
        assert seen_busy
    saved = client.get(f"/api/v1/agent/sessions/{sid}").json()["messages"]
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[1]["content"].startswith("w0") and "never" not in saved[1]["content"]
    client.delete(f"/api/v1/agent/sessions/{sid}")
