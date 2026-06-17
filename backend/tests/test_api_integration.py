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

    with TestClient(app) as c:
        yield c


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
