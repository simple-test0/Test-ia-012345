"""Tests for the system router: console logs + shutdown."""

import logging

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c


def test_logs_endpoint_returns_recent_records(client):
    logging.getLogger("test.console").info("ligne de test pour la console")
    r = client.get("/api/v1/system/logs")
    assert r.status_code == 200
    logs = r.json()["logs"]
    assert isinstance(logs, list)
    assert any("ligne de test pour la console" in entry["message"] for entry in logs)
    entry = logs[-1]
    assert {"id", "ts", "level", "logger", "message"} <= set(entry)


def test_logs_endpoint_respects_limit(client):
    for i in range(5):
        logging.getLogger("test.console").info(f"limite {i}")
    r = client.get("/api/v1/system/logs", params={"limit": 3})
    assert r.status_code == 200
    assert len(r.json()["logs"]) == 3


def test_shutdown_writes_stop_flag_and_schedules_exit(client, monkeypatch, tmp_path):
    from api.routes import system

    monkeypatch.setattr(system, "BASE_DIR", tmp_path)
    monkeypatch.setattr(system, "_shutdown_sequence", lambda: None)

    r = client.post("/api/v1/system/shutdown")
    assert r.status_code == 200
    assert r.json()["status"] == "shutting_down"
    assert (tmp_path / ".run" / "stop.flag").exists()


def test_logs_websocket_streams_backlog(client):
    logging.getLogger("test.console").info("backlog websocket")
    with client.websocket_connect("/ws/logs") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "log"
        assert {"id", "level", "message"} <= set(msg)


# ── Manual pipeline management ────────────────────────────────────────────────


def test_loaded_pipelines_empty_by_default(client):
    r = client.get("/api/v1/image/pipelines")
    assert r.status_code == 200
    assert r.json() == {"loaded": []}


def test_load_unknown_model_404(client):
    r = client.post("/api/v1/image/models/nope/load")
    assert r.status_code == 404


def test_unload_not_loaded_model(client):
    r = client.post("/api/v1/image/models/sd15/unload")
    assert r.status_code == 200
    assert r.json()["status"] == "not_loaded"


def test_delete_unknown_job_404(client):
    r = client.delete("/api/v1/image/jobs/nope")
    assert r.status_code == 404
