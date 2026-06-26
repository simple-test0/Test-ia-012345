# AI Studio

## Build commands
```bash
make test          # backend pytest (no torch)
make lint-fix      # ruff --fix
make type-check    # mypy
make migrate       # alembic upgrade head
make dev           # backend + frontend
```

## Wiring — where to add things
- **Agent tool**: create `backend/services/agent/tools/<name>.py` + add import at `main.py:21` (marked `# CLAUDE:`)
- **REST route**: `backend/api/routes/<module>.py` + wire at `main.py:63` (marked `# CLAUDE:`)
- **Labs arch**: `backend/services/labs/architectures/<name>.py` + register at `architecture_registry.py:24` (marked `# CLAUDE:`)
- **Image model**: append `ModelInfo` to `model_registry.py:24` (marked `# CLAUDE:`)

## Gotchas
- ruff I001: blank line between third-party and local imports **even inside functions**
- Tool files self-register on import — missing import in lifespan = tool not found at runtime
- WS handlers use `AsyncSessionLocal()` directly; routes use `Depends(get_db)`
- Gated models (flux-dev, sd35) silently fail downloads without `HUGGINGFACE_TOKEN`

## Code style
- Fully async (routes, services, DB queries)
- No comments unless WHY is non-obvious
- HTTP errors: `raise HTTPException(status_code=..., detail="...")`
- New schemas → `backend/schemas/<domain>.py` (Pydantic v2 `BaseModel`)

## Skills disponibles
`/architecture` — carte complète du projet, flux de données, env vars
`/add-agent-tool` — ajouter un outil Ollama (template + câblage)
`/add-route` — ajouter une route REST FastAPI
`/add-arch` — ajouter une architecture Labs PyTorch
`/test` — référence des commandes de test
