# AI Studio — Guide Claude

## Stack
- **Backend**: FastAPI (async) · SQLAlchemy 2.0 async · SQLite via aiosqlite · Pydantic v2 Settings · Alembic
- **Frontend**: React 18 · Vite · TypeScript · Tailwind CSS · Radix UI · WebSocket native
- **AI**: Ollama (LLM + tool calling) · diffusers (Stable Diffusion, SDXL, FLUX, SD3.5) · PyTorch

## Arborescence critique

```
backend/
  main.py                          # app FastAPI + lifespan (imports tools ici)
  core/config.py                   # Settings (pydantic-settings, .env)
  core/database.py                 # get_db(), init_db()
  core/security.py                 # require_api_token dependency
  api/routes/{image_gen,agent,hardware,labs}.py   # REST — 1 router par domaine
  api/websockets/{image,agent,training}_ws.py     # WS — stream de progression
  services/agent/
    tool_registry.py               # @register_tool decorator + execute_tool()
    tools/{calculator,web_search,code_executor}.py  # auto-enregistrés à l'import
    planner.py                     # boucle ReAct : Ollama → tool → réponse
    ollama_client.py               # client async Ollama
  services/image_gen/
    model_registry.py              # MODELS dict : id → ModelSpec
    pipeline_manager.py            # charge/décharge les pipelines diffusers
    worker.py                      # consomme asyncio.Queue, émet WS events
  services/labs/
    architecture_registry.py       # ARCHITECTURE_REGISTRY dict + ArchitectureSpec
    architectures/{cnn,rnn,transformer,vit}.py
    trainer.py                     # subprocess isolé + pause/resume/stop
    dataset_manager.py             # téléchargement HF + Kaggle
  models/                          # SQLAlchemy ORM (ImageJob, TrainingRun, …)
  schemas/                         # Pydantic request/response schemas
  migrations/versions/             # Alembic
frontend/src/
  pages/                           # ImageGen, Agent, Labs, Hardware
  components/                      # UI réutilisable
  api/                             # fetch wrappers
  hooks/                           # useWebSocket, etc.
```

## Patterns essentiels

### Ajouter un outil agent
1. Créer `backend/services/agent/tools/mon_outil.py`
2. Décorer avec `@register_tool(name, description, parameters)` (voir `calculator.py`)
3. Ajouter l'import dans `backend/main.py` lifespan (ligne ~22)
4. Les outils peuvent être sync ou async — `execute_tool()` gère les deux

### Ajouter une route REST
1. Créer/compléter `backend/api/routes/mon_module.py` avec `router = APIRouter()`
2. Dans `backend/main.py` : `from api.routes import mon_module` puis `app.include_router(mon_module.router, prefix="/api/v1", dependencies=_auth)`

### Ajouter une architecture Labs
1. Créer `backend/services/labs/architectures/mon_arch.py` avec `build_mon_arch(config) -> nn.Module`
2. Dans `backend/services/labs/architecture_registry.py` : importer le builder et ajouter une `ArchitectureSpec` dans `ARCHITECTURE_REGISTRY`

### Ajouter un modèle image
- Éditer `backend/services/image_gen/model_registry.py` — ajouter une entrée `ModelSpec` dans `MODELS`

## Commandes courantes (Makefile à la racine)

```bash
make test          # tests backend rapides (sans torch)
make test-heavy    # tests GPU (marqueur heavy)
make test-front    # type-check + build frontend
make test-all      # test + test-front
make test-cov      # couverture de code

make lint          # ruff check
make lint-fix      # ruff check --fix
make type-check    # mypy (config: backend/mypy.ini)
make check         # lint + type-check + test + test-front

make dev           # démarre backend + frontend (./start.sh)
make dev-back      # backend seul (uvicorn --reload)
make dev-front     # frontend seul (vite dev)

make migrate       # alembic upgrade head
make migration msg="describe change"   # alembic revision --autogenerate

make install       # pip install deps + npm install + pre-commit install
```

Équivalents directs si Makefile indisponible :
```bash
cd backend && pytest -x -q
cd backend && ruff check .
cd backend && mypy .
cd frontend && npm run build
```

## Variables d'environnement (backend/.env)

| Variable | Défaut | Usage |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint Ollama |
| `HUGGINGFACE_TOKEN` | vide | modèles gated (FLUX, SD3.5) |
| `API_TOKEN` | vide | auth REST+WS (vide = ouvert) |
| `ENABLE_CODE_EXECUTOR` | `false` | exécution Python par l'agent |
| `MIN_FREE_DISK_MB` | `2048` | garde-fou téléchargements HF |

## Conventions de code

- **Async partout** côté backend : routes, services, DB queries
- **Pas de commentaires** sauf invariant non-évident
- **Schemas Pydantic** pour toutes les entrées/sorties REST (`backend/schemas/`)
- **Logger** via `logging.getLogger(__name__)` — pas de print
- Les WebSockets émettent des JSON `{"type": "...", "data": {...}}`
- Les exceptions silencieuses (`except: pass`) sont remplacées par `logger.debug`
- `ruff` est le linter — config dans `backend/ruff.toml`

## Tests

- Fichiers dans `backend/tests/`
- `conftest.py` fournit `async_client` (httpx), `db_session`, etc.
- Marqueur `@pytest.mark.heavy` pour les tests nécessitant torch/diffusers
- CI GitHub Actions : `.github/workflows/ci.yml` — exécute les tests non-heavy + `npm run build`

## Ce qui reste à faire (TODO.md)

- `img2img` (upload source + génération) — back + UI
- ControlNet (pose/depth/canny)
- Tests e2e torch/diffusers (marqueur `heavy` déjà en place)
