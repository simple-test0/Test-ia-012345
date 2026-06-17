# AI Studio

Local AI workstation — **image generation**, **chat agents** (Ollama), and a
training **Labs** (create → train → reinforce). Runs on consumer GPUs (6–24 GB)
and falls back to CPU. Multi-vendor: NVIDIA CUDA, AMD ROCm, Intel XPU, Apple MPS.

## Quick start (beginners)

You need **Python 3.10+** and **Node.js (LTS)** installed first.

### Windows
1. Download/clone this folder.
2. Double-click **`install.bat`** (installs everything, picks the right PyTorch
   for your GPU, and tunes the app to your hardware).
3. Double-click **`start.bat`**, then open <http://localhost:5173>.

### Linux / macOS
```bash
./install.sh      # one-click install + hardware optimisation
./start.sh        # launch, then open http://localhost:5173
```

That's it. The installer auto-detects your GPU and writes an optimised
`backend/.env` for you.

> 💬 For the chat agents, also install **[Ollama](https://ollama.com)** and pull a
> model the installer recommends for your card (e.g. `ollama pull llama3.1:8b`).
> 🔒 For gated image models (FLUX.1-dev, SD3.5), add `HUGGINGFACE_TOKEN=hf_...`
> to `backend/.env`.

## Project structure

```
.
├── install.sh / install.bat   # one-click setup (deps + GPU detection + tuning)
├── start.sh   / start.bat     # launch backend + frontend
├── scripts/optimize.py        # hardware detection → tuned backend/.env
├── backend/                   # FastAPI app
│   ├── main.py                # app entry (routers, lifespan, startup)
│   ├── api/routes/            # REST: hardware · image · agent · labs
│   ├── api/websockets/        # live streams: image · agent · training
│   ├── services/              # image_gen · agent · labs (the real work)
│   ├── hardware/              # accelerator detection + recommendations
│   ├── models/                # database models
│   └── requirements.txt
└── frontend/                  # React + Vite UI
    └── src/pages/             # ImageGeneration · Agent · Labs
```

See **[IMPROVEMENTS.md](IMPROVEMENTS.md)** for the full changelog and design notes.

## Re-optimise after a hardware change

```bash
python scripts/optimize.py          # detect + rewrite backend/.env
python scripts/optimize.py --print  # preview only, write nothing
```

The app also has an **“Auto-tune for my GPU”** button in the Labs and shows your
detected tier in the UI, so optimisation is available both at install time and
live.

## What gets tuned

`scripts/optimize.py` detects your accelerator + memory and picks: the
recommended image models & resolution, mixed-precision dtype, `torch.compile`,
attention backend, how many pipelines stay resident, the megapixel cap, and the
LLM size tier — all written to `backend/.env`.
