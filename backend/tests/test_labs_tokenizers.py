"""Tests for the tokenizer routes, training options endpoint and manager."""
import importlib.util
import io
import time

import pytest

_HAS_TORCH = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not _HAS_TORCH, reason="torch not installed")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c


def _wait_status(client, path, ready="ready", timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(path).json()
        if body["status"] in (ready, "error"):
            return body
        time.sleep(0.3)
    pytest.fail(f"timeout waiting for {path} to become {ready}")


# ── Static schemas ────────────────────────────────────────────────────────────


def test_training_options_endpoint(client):
    r = client.get("/api/v1/labs/training-options")
    assert r.status_code == 200
    body = r.json()
    assert "optimizer" in body["options"]
    assert "adamw" in body["options"]["optimizer"]["choices"]
    assert "warmup_cosine" in body["options"]["lr_scheduler"]["choices"]
    # every option belongs to a declared group
    for opt in body["options"].values():
        assert opt["group"] in body["groups"]


def test_tokenizer_algorithms_endpoint(client):
    r = client.get("/api/v1/labs/tokenizers/algorithms")
    assert r.status_code == 200
    body = r.json()
    ids = {a["id"] for a in body["algorithms"]}
    assert {"bpe", "wordpiece", "unigram", "wordlevel", "char"} <= ids
    assert "[PAD]" in body["default_special_tokens"]


# ── Validation errors ────────────────────────────────────────────────────────


def test_train_tokenizer_unknown_dataset_400(client):
    r = client.post(
        "/api/v1/labs/tokenizers",
        json={"name": "t", "dataset_id": "nope", "algorithm": "bpe"},
    )
    assert r.status_code == 400


def test_train_tokenizer_bad_algorithm_422(client):
    r = client.post(
        "/api/v1/labs/tokenizers",
        json={"name": "t", "dataset_id": "nope", "algorithm": "quantique"},
    )
    assert r.status_code == 422


def test_train_tokenizer_bad_vocab_422(client):
    r = client.post(
        "/api/v1/labs/tokenizers",
        json={"name": "t", "dataset_id": "nope", "algorithm": "bpe", "vocab_size": 2},
    )
    assert r.status_code == 422


def test_encode_unknown_tokenizer_404(client):
    r = client.post("/api/v1/labs/tokenizers/nope/encode", json={"text": "bonjour"})
    assert r.status_code == 404


def test_delete_unknown_tokenizer_404(client):
    r = client.delete("/api/v1/labs/tokenizers/nope")
    assert r.status_code == 404


def test_delete_unknown_run_404(client):
    r = client.delete("/api/v1/labs/runs/nope")
    assert r.status_code == 404


def test_run_with_not_ready_tokenizer_400(client):
    r = client.post(
        "/api/v1/labs/runs",
        json={
            "name": "r",
            "architecture": "lstm",
            "arch_config": {},
            "training_config": {"epochs": 1},
            "tokenizer_id": "nope",
        },
    )
    assert r.status_code == 400


# ── Full flow: upload corpus → train tokenizer → encode → delete ─────────────


def test_tokenizer_full_flow(client):
    corpus = "\n".join(
        ["le chat mange la souris", "la souris mange le fromage"] * 30
    ).encode("utf-8")
    r = client.post(
        "/api/v1/labs/datasets/upload",
        data={"name": "corpus-tok-test", "task_type": "nlp"},
        files={"files": ("corpus.txt", io.BytesIO(corpus), "text/plain")},
    )
    assert r.status_code == 200
    ds_id = r.json()["id"]
    ds = _wait_status(client, f"/api/v1/labs/datasets/{ds_id}")
    assert ds["status"] == "ready", ds.get("error_message")

    r = client.post(
        "/api/v1/labs/tokenizers",
        json={
            "name": "tok-test",
            "dataset_id": ds_id,
            "algorithm": "bpe",
            "vocab_size": 300,
            "min_frequency": 1,
        },
    )
    assert r.status_code == 200
    tok_id = r.json()["id"]
    tok = _wait_status(client, f"/api/v1/labs/tokenizers/{tok_id}")
    assert tok["status"] == "ready", tok.get("error_message")
    assert tok["actual_vocab_size"] > 0
    assert tok["stats"]["num_texts"] == 60

    r = client.post(
        f"/api/v1/labs/tokenizers/{tok_id}/encode",
        json={"text": "le chat mange le fromage"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["num_tokens"] > 0
    assert len(body["tokens"]) == len(body["ids"])

    assert client.delete(f"/api/v1/labs/tokenizers/{tok_id}").status_code == 200
    assert client.get(f"/api/v1/labs/tokenizers/{tok_id}").status_code == 404
    assert client.delete(f"/api/v1/labs/datasets/{ds_id}").status_code == 200


# ── Manager unit tests (no HTTP) ─────────────────────────────────────────────


def test_build_all_algorithms_train_and_encode():
    from services.labs.tokenizer_manager import (
        DEFAULT_SPECIAL_TOKENS,
        _build_tokenizer_and_trainer,
    )

    corpus = ["le chat mange la souris", "bonjour le monde"] * 20
    for algo in ("bpe", "wordpiece", "unigram", "wordlevel", "char"):
        tok, trainer = _build_tokenizer_and_trainer(
            algo, 200, 1, DEFAULT_SPECIAL_TOKENS, False, True
        )
        tok.train_from_iterator(corpus, trainer=trainer)
        enc = tok.encode("le chat")
        assert len(enc.ids) > 0, algo


def test_iter_dataset_texts_files(tmp_path):
    from services.labs.tokenizer_manager import _iter_dataset_texts

    (tmp_path / "a.txt").write_text("ligne un\nligne deux\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text('{"text": "depuis jsonl"}\n', encoding="utf-8")
    texts = list(_iter_dataset_texts(str(tmp_path)))
    assert "ligne un" in texts and "depuis jsonl" in texts


def test_iter_dataset_texts_empty_raises(tmp_path):
    from services.labs.tokenizer_manager import _iter_dataset_texts

    with pytest.raises((ValueError, FileNotFoundError)):
        list(_iter_dataset_texts(str(tmp_path / "absent")))
