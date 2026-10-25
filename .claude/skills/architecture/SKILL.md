---
name: architecture
description: Invoke when you need to understand the project structure, locate where a feature is implemented, trace an image generation or agent data flow, or check environment variables and DB schema — contains full file map and ASCII flow diagrams
---

# AI Studio — Architecture Reference

## Stack
- **Backend**: FastAPI (async) · SQLAlchemy 2.0 + aiosqlite · Pydantic v2 · Alembic
- **Frontend**: React 18 · Vite · TypeScript · Tailwind CSS · Radix UI
- **AI**: Ollama (LLM + native tool calling) · diffusers (SD/SDXL/FLUX/SD3.5) · PyTorch

## Complete file map

```
backend/
  main.py                          # FastAPI entrypoint — lifespan, routers, CORS
  core/config.py                   # Settings (pydantic-settings, reads .env)
  core/database.py                 # get_db(), AsyncSessionLocal, init_db(), Base
  core/security.py                 # require_api_token (REST dep), ws_token_ok (WS)
  hardware/detector.py             # get_hardware_info(), get_primary_vram_mb() — TTL cached
  hardware/recommender.py          # get_recommendations(hw) → dict of UI advice
  api/routes/image_gen.py          # REST /image/* — generate, list models, HF search/download
  api/routes/agent.py              # REST /agent/* — sessions CRUD, tools list, Ollama models
  api/routes/hardware.py           # REST /hardware/* — info, recommendations
  api/routes/labs.py               # REST /labs/* — architectures, datasets, training runs
  api/websockets/image_ws.py       # WS /ws/image/{job_id} — subscribe to generation events
  api/websockets/agent_ws.py       # WS /ws/agent/{session_id} — bidirectional chat
  api/websockets/training_ws.py    # WS /ws/training/{run_id} — live metrics
  api/websockets/manager.py        # ws_manager — broadcast/connect/disconnect
  services/agent/tool_registry.py  # @register_tool decorator, execute_tool(), list_tools()
  services/agent/tools/calculator.py   # tool: AST math eval (safe, anti-DoS)
  services/agent/tools/web_search.py   # tool: DuckDuckGo via ddgs
  services/agent/tools/code_executor.py # tool: Python sandbox (off by default)
  services/agent/planner.py        # ReactAgent: Ollama → tool loop → final response
  services/agent/ollama_client.py  # async Ollama client (native tool calling)
  services/image_gen/model_registry.py  # MODEL_REGISTRY list + resolve_model()
  services/image_gen/pipeline_manager.py # loads/unloads diffusers pipelines (LRU)
  services/image_gen/worker.py     # GenerationWorker: consumes Queue, emits WS events
  services/image_gen/hf_connector.py    # HF model search + download with byte-accurate progress
  services/labs/architecture_registry.py # ARCHITECTURE_REGISTRY dict + ArchitectureSpec
  services/labs/architectures/cnn.py    # build_cnn(config) → nn.Module
  services/labs/architectures/rnn.py    # build_rnn/lstm/gru(config) → nn.Module
  services/labs/architectures/transformer.py  # build_transformer(config) → nn.Module
  services/labs/architectures/vit.py    # build_vit(config) → nn.Module
  services/labs/trainer.py         # isolated subprocess + pause/resume/stop + checkpoints
  services/labs/dataset_manager.py # HF/Kaggle download + multi-format normalization
  models/image_job.py              # ORM ImageJob
  models/diffusion_model.py        # ORM DiffusionModel (HF downloaded models)
  models/training_run.py           # ORM TrainingRun
  models/agent_session.py          # ORM AgentSession (messages JSON, tools_used)
  models/dataset.py                # ORM Dataset
  schemas/                         # Pydantic request/response schemas
  migrations/versions/             # Alembic — initial migration exists
  tests/                           # pytest (see /test skill)
frontend/src/
  pages/{ImageGen,Agent,Labs,Hardware}.tsx
  api/                             # typed fetch wrappers → /api/v1/
  hooks/                           # useWebSocket, etc.
  components/                      # shared UI (Toasts, etc.)
```

## Data flows

### Image generation
```
POST /api/v1/image/generate
  → resolve_model() → MODEL_REGISTRY or DB DiffusionModel
  → asyncio.Queue (app.state, maxsize=50)
  → GenerationWorker [background asyncio task]
    → pipeline_manager.get_pipeline(repo_id)  ← loads diffusers
    → pipeline(prompt, ...) → images[]
    → ws_manager.send(job_id, event)
WS /ws/image/{job_id}  ← client subscribes for events
```

### Agent ReAct loop
```
WS /ws/agent/{session_id}
  → receives {"content": "...", "model_id": "llama3"}
  → loads AgentSession.messages from DB
  → ReactAgent.run(messages)
    → OllamaClient.chat(model, messages, tools=tools_as_ollama_schema())
    → if tool_call → execute_tool(name, args)
    → loops until final response
  → ws_manager.send(session_id, event)  ← {"type": "token"|"tool_call"|"done"}
  → saves messages + tools_used in AgentSession (DB)
```

## Environment variables (backend/.env)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `HUGGINGFACE_TOKEN` | empty | Gated models (FLUX-dev, SD3.5) |
| `API_TOKEN` | empty | REST+WS auth (empty = open in dev) |
| `ENABLE_CODE_EXECUTOR` | `false` | Python sandbox agent tool |
| `CODE_EXECUTOR_TIMEOUT` | `15` | Sandbox timeout (seconds) |
| `CODE_EXECUTOR_MAX_MEMORY_MB` | `512` | Sandbox memory limit |
| `MIN_FREE_DISK_MB` | `2048` | HF download disk guard |
| `MAX_QUEUE_SIZE` | `50` | Image generation queue |
| `MAX_PIPELINES_LOADED` | `1` | Diffusers pipelines in memory |

## DB models (SQLAlchemy ORM, async)
- `ImageJob`: id, status, prompt, images (JSON thumbnails), model_id, created_at
- `DiffusionModel`: id, repo_id, status, min_vram_mb, recommended_steps, default_cfg
- `TrainingRun`: id, arch, config, status, metrics, checkpoint_path
- `AgentSession`: id, name, messages (JSON array), tools_used (JSON array)
- `Dataset`: id, name, source, path, format, size_mb
