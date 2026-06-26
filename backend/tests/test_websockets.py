"""WebSocket endpoint tests.

Uses FastAPI's built-in TestClient.websocket_connect() — no extra deps needed.
Gated on torch like test_api_integration.py because the app lifespan
imports the image generation worker which depends on torch.
"""
import importlib.util
import json

import pytest

_HAS_TORCH = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not _HAS_TORCH, reason="torch not installed")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as c:
        yield c


# ── /ws/image/{job_id} ───────────────────────────────────────────────────────

def test_image_ws_connects_and_disconnects(client):
    """Client can connect and cleanly disconnect without error."""
    with client.websocket_connect("/ws/image/test-job-123"):
        pass  # clean disconnect on context exit


def test_image_ws_rejects_wrong_token(client, monkeypatch):
    """When API_TOKEN is set, a wrong token closes with 1008."""
    import core.security as sec
    monkeypatch.setattr(sec, "ws_token_ok", lambda t: False)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/image/job-xyz"):
            pass


# ── /ws/agent/{session_id} ───────────────────────────────────────────────────

def test_agent_ws_connects(client):
    """Agent WS accepts a connection (session not found is handled gracefully)."""
    with client.websocket_connect("/ws/agent/nonexistent-session") as ws:
        # Send a message — session doesn't exist, expect an error event back
        ws.send_text(json.dumps({"content": "hello", "model_id": "llama3"}))
        data = ws.receive_json()
        assert data.get("type") == "error"
        assert "not found" in data.get("message", "").lower()


def test_agent_ws_ignores_empty_content(client):
    """Agent WS silently ignores messages with no content."""
    with client.websocket_connect("/ws/agent/nonexistent-session") as ws:
        ws.send_text(json.dumps({"content": "  ", "model_id": "llama3"}))
        # No response expected — the handler `continue`s on empty content
        # Verify connection stays alive by sending another valid message
        ws.send_text(json.dumps({"content": "hi", "model_id": "llama3"}))
        data = ws.receive_json()
        assert "type" in data


def test_agent_ws_ignores_invalid_json(client):
    """Malformed JSON is silently dropped, connection stays alive."""
    with client.websocket_connect("/ws/agent/nonexistent-session") as ws:
        ws.send_text("not json {{")
        # Follow up with valid JSON to confirm connection is still open
        ws.send_text(json.dumps({"content": "ping", "model_id": "llama3"}))
        data = ws.receive_json()
        assert "type" in data


def test_agent_ws_rejects_wrong_token(client, monkeypatch):
    """Bad token closes the agent WS with 1008."""
    import core.security as sec
    monkeypatch.setattr(sec, "ws_token_ok", lambda t: False)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/agent/any-session"):
            pass


# ── /ws/training/{run_id} (passive subscribe channel) ───────────────────────

def test_training_ws_connects(client):
    """Training WS accepts a connection and stays open passively."""
    with client.websocket_connect("/ws/training/test-run-999"):
        pass
