# AI Studio — Oracle Claude

> Ce fichier est la source unique de vérité pour naviguer le projet.
> Claude : lis ce fichier, tu n'as pas besoin d'en ouvrir d'autres pour comprendre l'architecture.

---

## Référence rapide — tâche → fichier → action

| Tâche | Fichier | Action |
|---|---|---|
| Ajouter un outil agent | `backend/services/agent/tools/<nom>.py` (créer) + `backend/main.py:21` (import) | voir §Outil agent |
| Ajouter une route REST | `backend/api/routes/<module>.py` + `backend/main.py:64-68` | voir §Route REST |
| Ajouter une architecture Labs | `backend/services/labs/architectures/<nom>.py` + `backend/services/labs/architecture_registry.py:1-10` (import) + ligne 23 (dict) | voir §Architecture Labs |
| Ajouter un modèle image | `backend/services/image_gen/model_registry.py:23` | ajouter `ModelInfo(...)` dans `MODEL_REGISTRY` |
| Changer la config | `backend/core/config.py:8` | ajouter un champ `Settings` |
| Modifier la DB | `backend/models/<modele>.py` puis `make migration msg="..."` | SQLAlchemy ORM async |
| Modifier l'UI | `frontend/src/pages/<Page>.tsx` | React + Tailwind + Radix UI |
| Ajouter un schema API | `backend/schemas/<domaine>.py` | Pydantic v2 BaseModel |
| Lancer les tests | `make test` | voir §Commandes |

---

## Stack

- **Backend** : FastAPI (async) · SQLAlchemy 2.0 + aiosqlite · Pydantic v2 · Alembic
- **Frontend** : React 18 · Vite · TypeScript · Tailwind CSS · Radix UI
- **AI** : Ollama (LLM + tool calling natif) · diffusers (SD/SDXL/FLUX/SD3.5) · PyTorch
- **Tests** : pytest-asyncio · httpx · ruff · mypy

---

## Carte des fichiers (un fichier = une ligne)

```
backend/
  main.py                          # Entrypoint FastAPI : lifespan, routers, middleware
  core/config.py                   # Settings pydantic-settings (.env)
  core/database.py                 # get_db(), AsyncSessionLocal, init_db(), Base
  core/security.py                 # require_api_token (REST dep), ws_token_ok (WS)
  hardware/detector.py             # get_hardware_info(), get_primary_vram_mb() — mis en cache
  hardware/recommender.py          # get_recommendations(hw) → dict de conseils
  api/routes/image_gen.py          # REST /image/* — génération, modèles, HF search/download
  api/routes/agent.py              # REST /agent/* — sessions, outils, modèles Ollama
  api/routes/hardware.py           # REST /hardware/* — info GPU/CPU, recommandations
  api/routes/labs.py               # REST /labs/* — architectures, datasets, runs
  api/websockets/image_ws.py       # WS /ws/image/{job_id} — subscribe aux events d'un job
  api/websockets/agent_ws.py       # WS /ws/agent/{session_id} — chat bidirectionnel
  api/websockets/training_ws.py    # WS /ws/training/{run_id} — métriques live
  api/websockets/manager.py        # ws_manager — broadcast/connect/disconnect
  services/agent/tool_registry.py  # @register_tool, execute_tool(), list_tools()
  services/agent/tools/calculator.py   # outil : calcul mathématique AST (safe)
  services/agent/tools/web_search.py   # outil : DuckDuckGo via ddgs
  services/agent/tools/code_executor.py # outil : Python sandbox (désactivé par défaut)
  services/agent/planner.py        # ReactAgent : boucle Ollama → tool → réponse
  services/agent/ollama_client.py  # OllamaClient async (chat + tool calling natif)
  services/image_gen/model_registry.py  # MODEL_REGISTRY list + resolve_model()
  services/image_gen/pipeline_manager.py # charge/décharge pipelines diffusers (LRU)
  services/image_gen/worker.py     # GenerationWorker : consomme Queue, émet WS events
  services/image_gen/hf_connector.py    # search/download HF models avec progression
  services/labs/architecture_registry.py # ARCHITECTURE_REGISTRY + ArchitectureSpec
  services/labs/architectures/cnn.py    # build_cnn(config) → nn.Module
  services/labs/architectures/rnn.py    # build_rnn/lstm/gru(config) → nn.Module
  services/labs/architectures/transformer.py  # build_transformer(config) → nn.Module
  services/labs/architectures/vit.py    # build_vit(config) → nn.Module
  services/labs/trainer.py         # subprocess isolé — pause/resume/stop + checkpoints
  services/labs/dataset_manager.py # téléchargement HF/Kaggle + normalisation formats
  models/image_job.py              # ORM ImageJob (id, status, images, prompt…)
  models/diffusion_model.py        # ORM DiffusionModel (modèles téléchargés HF)
  models/training_run.py           # ORM TrainingRun
  models/agent_session.py          # ORM AgentSession (id, messages JSON, tools_used)
  models/dataset.py                # ORM Dataset
  schemas/                         # Pydantic request/response schemas
  migrations/versions/             # Alembic — une migration initiale existante
  tests/                           # pytest — voir §Tests
frontend/src/
  pages/ImageGen.tsx               # Page génération d'images
  pages/Agent.tsx                  # Page chat agent
  pages/Labs.tsx                   # Page training
  pages/Hardware.tsx               # Page infos matériel
  api/                             # fetch wrappers vers /api/v1/
  hooks/                           # useWebSocket, etc.
  components/                      # UI partagée (Toasts, etc.)
```

---

## Extension points — patterns exacts

### Outil agent (`@register_tool`)

**Fichier à créer** : `backend/services/agent/tools/<nom>.py`
```python
from services.agent.tool_registry import register_tool

@register_tool(
    name="<nom>",
    description="<phrase courte — envoyée à Ollama à chaque appel, garder concise>",
    parameters={
        "type": "object",
        "properties": {
            "<param>": {"type": "string", "description": "<desc>"},
        },
        "required": ["<param>"],
    },
)
async def <nom>(<param>: str) -> str:  # sync ou async, les deux marchent
    ...
    return str(result)
```

**Câblage** : `backend/main.py:21-23` — ajouter dans le bloc `lifespan` :
```python
import services.agent.tools.<nom>  # noqa: F401
```

Les outils s'auto-enregistrent à l'import dans `_registry` (`tool_registry.py:16`).

---

### Route REST

**Fichier** : `backend/api/routes/<module>.py`
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db

router = APIRouter(prefix="/<ressource>", tags=["<tag>"])

@router.get("/", response_model=list[MonSchema])
async def list_items(db: AsyncSession = Depends(get_db)):
    ...
```

**Câblage** : `backend/main.py:64-68` — ajouter :
```python
from api.routes import <module>
app.include_router(<module>.router, prefix="/api/v1", dependencies=_auth)
```

Règles : préfixe `/api/v1/` appliqué par `main.py` (ne pas le dupliquer). Auth globale via `_auth`. Schemas dans `backend/schemas/<domaine>.py`.

---

### Architecture Labs (`ArchitectureSpec`)

**Fichier à créer** : `backend/services/labs/architectures/<nom>.py`
```python
import torch.nn as nn

def build_<nom>(config: dict) -> nn.Module:
    return Mon<Nom>(**config)

class Mon<Nom>(nn.Module):
    def __init__(self, hidden_size=256, num_classes=10, **kw):
        super().__init__()
        ...
    def forward(self, x):
        ...
```

**Câblage** : `backend/services/labs/architecture_registry.py`
- Ligne 1-10 : ajouter `from services.labs.architectures.<nom> import build_<nom>`
- Ligne 23 (`ARCHITECTURE_REGISTRY`) : ajouter une entrée :
```python
"<nom>": ArchitectureSpec(
    id="<nom>", name="<Nom complet>",
    description="<affiché dans l'UI>",
    builder=build_<nom>,
    default_config={"hidden_size": 256, "num_classes": 10},
    task_types=["classification"],   # parmi: classification, nlp, detection
    min_vram_mb=512,
    param_schema={
        "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
    },
    tags=["<tag>"],
),
```

---

### Modèle image (`ModelInfo`)

**Fichier** : `backend/services/image_gen/model_registry.py:23`
Ajouter dans `MODEL_REGISTRY` :
```python
ModelInfo(
    id="<id-unique>",
    name="<Nom affiché>",
    description="<desc UI>",
    pipeline_class="StableDiffusionPipeline",  # ou XL/Flux/SD3
    repo_id="org/repo-hf",
    min_vram_mb=3000,
    recommended_steps=25,
    default_cfg=7.5,
    default_width=512, default_height=512,
    tags=["<tag>"],
    gated=False,   # True si licence HF requise
),
```

---

## Flux de données

### Génération d'image
```
POST /api/v1/image/generate
  → image_gen.py route
  → resolve_model() → MODEL_REGISTRY ou DB DiffusionModel
  → asyncio.Queue (maxsize=50, dans app.state)
  → GenerationWorker.run() [tâche asyncio background]
    → pipeline_manager.get_pipeline(repo_id)  ← charge diffusers
    → pipeline(prompt, ...) → images[]
    → ws_manager.send(job_id, event)
WS /ws/image/{job_id}  ← client subscribe pour recevoir les events
```

### Agent ReAct
```
WS /ws/agent/{session_id}
  → agent_ws.py reçoit {"content": "...", "model_id": "llama3"}
  → charge AgentSession.messages depuis DB
  → ReactAgent.run(messages)
    → OllamaClient.chat(model, messages, tools=tools_as_ollama_schema())
    → si tool_call → execute_tool(name, args)
    → boucle jusqu'à réponse finale
  → ws_manager.send(session_id, event)  ← {"type": "token"|"tool_call"|"done"}
  → sauvegarde messages + tools_used dans AgentSession (DB)
```

---

## Commandes (Makefile à la racine)

```bash
make test          # pytest -x -q  (sans torch, rapide)
make test-heavy    # pytest -m heavy  (GPU requis)
make test-cov      # couverture de code
make test-front    # npm run build (type-check + build)
make test-all      # test + test-front

make lint          # ruff check .
make lint-fix      # ruff check . --fix
make type-check    # mypy .  (config: backend/mypy.ini)
make check         # lint + type-check + test + test-front

make dev           # ./start.sh
make dev-back      # uvicorn main:app --reload
make dev-front     # npm run dev

make migrate                       # alembic upgrade head
make migration msg="describe"      # alembic revision --autogenerate

make install       # pip install deps + npm install + pre-commit install
```

---

## Variables d'environnement (`backend/.env`)

| Variable | Défaut | Usage |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint Ollama |
| `HUGGINGFACE_TOKEN` | vide | modèles gated (FLUX-dev, SD3.5) |
| `API_TOKEN` | vide | auth REST+WS (vide = ouvert en dev) |
| `ENABLE_CODE_EXECUTOR` | `false` | outil Python sandbox de l'agent |
| `CODE_EXECUTOR_TIMEOUT` | `15` | timeout sandbox (secondes) |
| `CODE_EXECUTOR_MAX_MEMORY_MB` | `512` | limite mémoire sandbox |
| `MIN_FREE_DISK_MB` | `2048` | garde-fou téléchargements HF |
| `MAX_QUEUE_SIZE` | `50` | taille max queue de génération |
| `MAX_PIPELINES_LOADED` | `1` | pipelines diffusers en mémoire simultanément |

---

## Gotchas (comportements non évidents)

- **Outils agent** : s'enregistrent via l'import dans lifespan (`main.py:21-23`). Si l'import est absent, l'outil n'existe pas à l'exécution même si le fichier est là.
- **`AsyncSessionLocal` vs `get_db()`** : les WebSocket handlers utilisent `AsyncSessionLocal()` directement (contexte long-lived). Les routes REST utilisent `Depends(get_db)`.
- **Hardware cache** : `get_primary_vram_mb()` utilise un cache TTL pour éviter des appels `psutil` bloquants à chaque requête.
- **Images dans l'historique** : les vignettes sont encodées en `data:image/jpeg;base64` (JPEG compressé), pas PNG — payload intentionnellement allégé.
- **Migrations** : le projet a une auto-migration légère de dev (ajout de colonnes manquantes) ET Alembic. En prod, utiliser uniquement Alembic.
- **code_executor** : désactivé par défaut (`ENABLE_CODE_EXECUTOR=false`). Quand activé, tourne avec `python -I`, timeout, rlimits mémoire+CPU+fichiers (POSIX).
- **Modèles gated** : FLUX-dev et SD3.5 nécessitent `HUGGINGFACE_TOKEN` + acceptation de licence sur HF. Sans token, le download échoue silencieusement.
- **ruff** : règle I001 active (isort) — ligne vide obligatoire entre imports tiers et imports locaux, y compris dans les corps de fonctions.

---

## Tests — carte des fichiers

| Fichier | Couvre |
|---|---|
| `test_calculator.py` | outil calculatrice (AST eval, anti-DoS) |
| `test_tool_registry.py` | registration + execute_tool() sync/async |
| `test_planner.py` | boucle ReAct de ReactAgent (Ollama mocké) |
| `test_model_registry.py` | MODEL_REGISTRY + resolve_model() |
| `test_recommender.py` | get_recommendations() |
| `test_trainer_dataset.py` | Labs trainer + dataset_manager |
| `test_api_integration.py` | toutes les routes REST (httpx, torch skipif) |
| `test_websockets.py` | /ws/image, /ws/agent, /ws/training (torch skipif) |
| `test_code_executor.py` | sandbox Python (timeout, limites) |
| `test_hf_and_security.py` | HF connector + auth token |
| `test_e2e_heavy.py` | e2e complet (marqué `@pytest.mark.heavy`) |

`conftest.py` fournit : `db_session` (SQLite mémoire async, toutes tables créées).

---

## TODO restant

- `img2img` : upload d'image source + génération — back (`worker.py`) + UI (`ImageGen.tsx`)
- ControlNet : pipeline pose/depth/canny — nouveau `pipeline_class` + UI
- Tests e2e torch/diffusers (marqueur `heavy` déjà en place, CI les skip)
