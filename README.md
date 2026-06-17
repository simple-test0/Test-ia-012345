# AI Studio

A local, all-in-one AI web app: **image generation**, **LLM agents with tools**, and a
**training lab** — all running on your own machine, hardware-aware.

- **Backend:** FastAPI (async), SQLAlchemy 2.0 + SQLite, WebSockets for live progress.
- **Frontend:** React + Vite + TypeScript + Tailwind + Radix UI.

## Features

### 🖼️ Image generation
- Stable Diffusion 1.5 / SDXL / SDXL-Turbo, plus FLUX.1 and SD 3.5 (gated).
- **Hugging Face connector**: search and download *any* text-to-image model from the UI;
  downloaded models persist and appear under "Téléchargés". Models are never version-pinned
  (always the latest `main`).
- Live step previews over WebSocket, queue, selectable sampler, VRAM-aware compatibility.

### 🤖 Agents
- Chat backed by a local **Ollama** model, using Ollama's **native tool calling**
  (with a regex fallback). Built-in tools: `web_search` (DuckDuckGo via `ddgs`),
  `calculator` (safe AST evaluator), `code_executor` (disabled by default — see Security).

### 🧪 Labs
- Train CNN / RNN / LSTM / GRU / Transformer / ViT in an isolated subprocess with
  pause/resume/stop, checkpoints, and live metrics. Download datasets from Hugging Face.

### 🧠 Hardware-aware
- Detects GPU/VRAM/CPU/RAM and recommends models, batch size, precision, offloading, etc.

## Requirements
- Python 3.11+, Node 20+
- (Optional) NVIDIA GPU + CUDA for fast image generation / training
- (Optional) [Ollama](https://ollama.com) running locally for the agent

## Quick start

```bash
./start.sh
```

This creates a Python venv, installs deps, and starts:
- backend on http://localhost:8000
- frontend on http://localhost:5173

Run `MODE=prod ./start.sh` to start the backend without auto-reload.

### Manual

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121
uvicorn main:app --reload

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

## Configuration

Copy `backend/.env.example` to `backend/.env`:

| Variable | Purpose |
| --- | --- |
| `OLLAMA_BASE_URL` | Ollama endpoint (default `http://localhost:11434`) |
| `HUGGINGFACE_TOKEN` | Required to download **gated** models (FLUX.1-dev, SD 3.5) |
| `API_TOKEN` | If set, REST needs header `X-API-Token` and WS needs `?token=` (see Security) |
| `ENABLE_CODE_EXECUTOR` | Set `true` to allow the agent to run Python (off by default) |
| `MIN_FREE_DISK_MB` | Refuse HF downloads below this free-disk margin |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | Optional, for Kaggle datasets |

For the frontend to send the token, build with `VITE_API_TOKEN=<token>`.

## Security
- `code_executor` runs arbitrary Python. It is **disabled by default**; enable it only in an
  isolated environment. When enabled it runs with `-I` isolation, a timeout, and memory/file
  limits (POSIX).
- Optional shared-token auth (`API_TOKEN`) protects REST + WebSocket endpoints. Because the
  REST check uses a custom header, it isn't exploitable via CSRF.

## Testing

```bash
cd backend && pip install -r requirements-dev.txt && pytest      # backend unit tests
cd frontend && npm run build                                     # type-check + build
```

CI runs both on every push/PR (`.github/workflows/ci.yml`).

## Docker

```bash
docker compose up --build
```

See `docker-compose.yml` (backend, frontend, optional Ollama). GPU passthrough requires the
NVIDIA Container Toolkit.

## Project layout

```
backend/   FastAPI app — api/ (routes, websockets), services/ (image_gen, agent, labs),
           models/ (DB), hardware/ (detection + recommendations), core/ (config, db, security)
frontend/  React app — src/pages, src/components, src/api, src/hooks
```

See `TODO.md` for remaining enhancements.
