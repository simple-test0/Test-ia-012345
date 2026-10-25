# AI Studio

## INVOKE A SKILL FIRST — before implementing anything
| Task | Skill |
|---|---|
| Add / create an agent tool for Ollama | `/add-agent-tool` |
| Add / create a REST route or API endpoint | `/add-route` |
| Add / create a Labs neural network architecture | `/add-arch` |
| Run, write, or debug tests | `/test` |
| Understand the project structure, find a file, trace a flow | `/architecture` |

The skill router hook injects a reminder automatically — but always invoke the relevant skill manually if unsure.

---

## Wiring — exact locations (marked `# CLAUDE:` in code)
- **Agent tool**: `backend/services/agent/tools/<name>.py` + import at `main.py:21`
- **REST route**: `backend/api/routes/<module>.py` + wire at `main.py:63`
- **Labs arch**: `backend/services/labs/architectures/<name>.py` + register at `architecture_registry.py:24`
- **Image model**: append `ModelInfo` to `model_registry.py:24`

## Gotchas
- ruff I001: blank line between third-party and local imports **even inside functions**
- Missing import in `main.py` lifespan = tool not registered at runtime
- WS handlers: `AsyncSessionLocal()` — routes: `Depends(get_db)`
- Gated models (flux-dev, sd35) silently fail without `HUGGINGFACE_TOKEN`

## Commands
```bash
make test       make lint-fix     make type-check
make migrate    make dev          make test-front
```

## Code style
- Fully async · No comments unless WHY is non-obvious · `raise HTTPException(...)` for errors
