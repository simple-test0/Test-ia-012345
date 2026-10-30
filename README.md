# AI Studio

A local, all-in-one AI web app: **image generation**, **LLM agents with tools**, and a
**training lab** — all running on your own machine, hardware-aware.

- **Backend:** FastAPI (async), SQLAlchemy 2.0 + SQLite (WAL), WebSockets for live progress.
- **Frontend:** React + Vite + TypeScript + Tailwind.
- **Runs on:** Linux, Windows (native `start.bat`, WSL or Docker) and macOS — NVIDIA GPU (CUDA),
  Apple Silicon GPU (MPS) or CPU only.

## Quick start

```bash
./start.sh
```

That's it. The launcher:

- picks a compatible Python (3.10 – 3.12) and creates `backend/.venv`;
- installs the right PyTorch build for the machine (CUDA if `nvidia-smi` works, CPU-only
  wheels on Linux without GPU, standard wheels on macOS);
- reinstalls dependencies only when `requirements.txt` / `package-lock.json` change;
- creates `backend/.env` from the example on first run;
- starts backend + frontend, waits until they answer, then opens the browser.

| Command | What it does |
| --- | --- |
| `./start.sh` | Dev mode: backend with auto-reload on :8000, UI on http://localhost:5173 |
| `MODE=prod ./start.sh` | Builds the UI once and serves **everything on one port** (http://localhost:8000) |
| `NO_BROWSER=1 ./start.sh` | Don't open a browser |
| `BACKEND_PORT=8010 FRONTEND_PORT=5180 ./start.sh` | Other ports |
| `TORCH_VARIANT=cpu ./start.sh` | Force a PyTorch build (`cuda`, `cpu`, `default`) |

The dev server also listens on the LAN, so the UI works from a phone or tablet
(`http://<your-ip>:5173`).

### Windows

Double-click **`start.bat`** (or run `.\start.ps1` in PowerShell). Same behaviour as
`start.sh`: picks Python 3.10–3.12 via the `py` launcher, installs the CUDA build when
`nvidia-smi` works, opens the browser. Options: `start.bat -Prod`, `-NoBrowser`,
`-BackendPort 8010`, `-TorchVariant cpu`.

### Requirements
- Python **3.10, 3.11 or 3.12** (PyTorch 2.4 has no wheels for 3.13 yet), Node **18+**
- Optional: NVIDIA GPU + driver, or an Apple Silicon Mac, for fast generation/training
- Optional: [Ollama](https://ollama.com) for the agent (`ollama pull llama3.2`)

### Manual setup

```bash
# Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                       # macOS / CPU
# NVIDIA: pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121
uvicorn main:app --reload

# Frontend (in another terminal)
cd frontend
npm ci
npm run dev
```

## Features

### 🖼️ Image generation
- Stable Diffusion 1.5 / SDXL / SDXL-Turbo, FLUX.1 and SD 3.5 (gated) — plus **any**
  text-to-image model from Hugging Face, searchable and downloadable from the UI.
- **Image-to-image**: drop, paste (Ctrl+V) or pick a source image — or reuse any result
  with "Utiliser comme source" — and choose how strongly it is transformed. The source keeps
  its aspect ratio; reusing a job's settings restores its source too.
- Queue that never blocks: live position in queue, **cancel** queued or running jobs.
- Live step previews (cheap latent→RGB approximation, no extra VAE pass per step).
- Picking a model applies its recommended steps / CFG / size; aspect-ratio presets.
- History with lazy-loaded thumbnails, full-size **lightbox + PNG download**,
  "reuse settings" (same seed), copy prompt, delete; settings are remembered.
- LoRA adapters, selectable sampler, `Ctrl+Enter` to generate.

### 🤖 Agents
- Chat with a local **Ollama** model with **streamed answers** rendered as Markdown,
  native tool calling (regex fallback). Tools: `web_search` (DuckDuckGo), `calculator`
  (safe AST evaluator), `code_executor` (disabled by default — see Security).
- Conversations are saved: history reloads, per-session system prompt, auto-titled
  sessions, delete; typing a message creates a session automatically.
- **Stop** button: interrupts the answer (Ollama stops generating) and keeps what was
  already written.

### 🧪 Labs
- Train CNN / RNN / LSTM / GRU / Transformer / ViT in an isolated process (CUDA, MPS or CPU)
  with pause / resume / stop, checkpoints, live metrics and loss/accuracy charts.
- Datasets from Hugging Face or **local file upload**; export to ONNX / safetensors and
  download from the UI. Crashed training processes are detected and reported.

### 🧠 Hardware-aware
- Detects GPU / VRAM / Apple Silicon / CPU / RAM and recommends models, batch size,
  precision, offloading, etc.

### 🛟 Robustness
- Restart-safe: jobs, trainings and downloads interrupted by a restart are marked as such
  instead of spinning forever.
- WebSockets reconnect automatically (with backoff) and resync state; polling fallback.
- Heavy work (model loading, generation, tools, file I/O) never runs on the event loop.
- Ctrl+C stops the app within seconds even during a multi-GB model download (it resumes
  next time); set `FAST_SHUTDOWN=false` to wait for running work instead.

## Configuration

`backend/.env` (created from `backend/.env.example` on first launch):

| Variable | Purpose |
| --- | --- |
| `OLLAMA_BASE_URL` | Ollama endpoint (default `http://localhost:11434`) |
| `OLLAMA_TIMEOUT` | Max seconds for one model reply (default 300) |
| `HUGGINGFACE_TOKEN` | Required to download **gated** models (FLUX.1-dev, SD 3.5) |
| `API_TOKEN` | If set, REST needs header `X-API-Token` and WS needs `?token=` (see Security) |
| `DATA_DIR` | Where images, models, datasets and the DB live (default `./data`) |
| `CORS_ORIGINS` | Extra allowed browser origins, comma-separated |
| `ENABLE_CODE_EXECUTOR` | Set `true` to allow the agent to run Python (off by default) |
| `MIN_FREE_DISK_MB` | Refuse HF downloads below this free-disk margin |
| `MAX_UPLOAD_MB` | Max size of one dataset upload (default 2048) |
| `MAX_QUEUE_SIZE` / `MAX_PIPELINES_LOADED` | Generation queue length / pipelines kept in memory |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | Optional, for Kaggle datasets |

For the frontend to send the token, build with `VITE_API_TOKEN=<token>`.

## Security
- `code_executor` runs arbitrary Python. It is **disabled by default**; enable it only in an
  isolated environment. When enabled it runs with `-I` isolation, a timeout, and memory/file
  limits (POSIX).
- Optional shared-token auth (`API_TOKEN`, constant-time comparison) protects REST +
  WebSocket endpoints. Because the REST check uses a custom header, it isn't exploitable via
  CSRF. Image files also accept `?token=` so `<img>` tags and download links work.
- Uploaded file names are sanitised (no path traversal) and uploads are size-limited.
- The servers listen on all interfaces: set `API_TOKEN` before using the app on a shared
  network.

## Testing

```bash
cd backend && pip install -r requirements-dev.txt && pytest      # unit + API + real training
cd frontend && npm run build                                     # type-check + build
```

CI runs both on every push/PR (`.github/workflows/ci.yml`) with CPU-only PyTorch, so the
API integration tests and an end-to-end training run are exercised. Tests that need
diffusers are marked `heavy` — run locally with `pytest -m heavy`.

## Database migrations

The app auto-creates tables on startup (plus a lightweight column auto-migration) for a
zero-config dev experience. For production, use Alembic:

```bash
cd backend
alembic upgrade head            # apply migrations
alembic revision --autogenerate -m "describe change"   # after model changes
```

## Docker

```bash
docker compose up --build        # UI on http://localhost:5173
```

CPU image by default. For NVIDIA GPUs install the NVIDIA Container Toolkit, build with
`docker compose build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121` and
uncomment the `deploy` block in `docker-compose.yml`. Data persists in `./data`.

## Project layout

```
backend/   FastAPI app — api/ (routes, websockets), services/ (image_gen, agent, labs),
           models/ (DB), hardware/ (detection + recommendations), core/ (config, db, security)
frontend/  React app — src/pages, src/components, src/api, src/hooks
```

See `TODO.md` for remaining enhancements.
