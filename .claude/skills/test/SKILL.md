---
name: test
description: Reference for running tests — which command to use, which file covers what, and test infrastructure details
---

# Test Reference

## Commands

```bash
make test          # backend unit tests — no torch, fast, runs in CI
make test-heavy    # tests requiring GPU (pytest -m heavy)
make test-cov      # coverage report (term-missing)
make test-front    # TypeScript type-check + frontend build
make test-all      # test + test-front

# Targeted runs
cd backend && pytest tests/<file>.py -v          # single file
cd backend && pytest tests/<file>.py::test_<fn>  # single test
cd backend && pytest -x -q                       # stop on first failure
cd backend && pytest -k "keyword"                # keyword filter
```

## File → what it covers

| File | Covers |
|---|---|
| `test_calculator.py` | AST eval, anti-DoS exponent guard |
| `test_tool_registry.py` | @register_tool, execute_tool() sync/async |
| `test_planner.py` | ReactAgent ReAct loop (Ollama mocked) |
| `test_model_registry.py` | MODEL_REGISTRY, resolve_model() curated + DB |
| `test_recommender.py` | get_recommendations() hardware profiles |
| `test_trainer_dataset.py` | Labs trainer + dataset_manager formats |
| `test_api_integration.py` | All REST routes via httpx (skipped without torch) |
| `test_websockets.py` | /ws/image, /ws/agent, /ws/training (skipped without torch) |
| `test_code_executor.py` | Python sandbox timeout + rlimits |
| `test_hf_and_security.py` | HF connector + API_TOKEN auth |
| `test_e2e_heavy.py` | Full e2e (marked `@pytest.mark.heavy`) |

## Infrastructure (conftest.py)

- `db_session` fixture: async SQLite in-memory, all tables created, auto-rollback
- Tests that need the full app use `TestClient(app)` — skipped if torch absent
- `@pytest.mark.heavy` = excluded from CI, run locally with GPU

## Adding a test

```python
import pytest

async def test_my_feature(db_session):  # inject db_session for DB access
    ...

# For tests needing the full app:
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from main import app            # blank line required before local imports (ruff I001)
    with TestClient(app) as c:
        yield c

def test_endpoint(client):
    r = client.get("/api/v1/my-route")
    assert r.status_code == 200
```
