#!/usr/bin/env bash
# AI Studio — one-click installer (Linux / macOS)
#
# For beginners: open a terminal in this folder and run:
#     ./install.sh
# It checks your tools, installs everything, picks the right PyTorch build for
# your GPU, builds the UI, and tunes the app to your hardware. Then run ./start.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "\033[33m!\033[0m %s\n" "$1"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$1"; exit 1; }

bold "=== AI Studio installer ==="
echo

# ── 1. Prerequisites ─────────────────────────────────────────────────────────
PY=""
for cand in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" &>/dev/null; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "Python 3.10+ not found. Install it from https://python.org and re-run."

PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
"$PY" -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' \
  || die "Python $PYVER is too old; need 3.10+."
ok "Python $PYVER ($PY)"

command -v node &>/dev/null || die "Node.js not found. Install the LTS from https://nodejs.org and re-run."
ok "Node $(node --version)"
command -v npm &>/dev/null || die "npm not found (it ships with Node.js)."

# ── 2. Detect the accelerator → pick the matching PyTorch build ───────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
TORCH_INDEX=""        # empty = default PyPI (CPU on Linux/Win, MPS on macOS)
ACCEL="CPU"

if command -v nvidia-smi &>/dev/null; then
  ACCEL="NVIDIA CUDA"
  # cu121 wheels run on all reasonably recent NVIDIA drivers (>=530).
  TORCH_INDEX="https://download.pytorch.org/whl/cu121"
elif command -v rocminfo &>/dev/null || [ -d /opt/rocm ]; then
  ACCEL="AMD ROCm"
  TORCH_INDEX="https://download.pytorch.org/whl/rocm6.2"
elif [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
  ACCEL="Apple Silicon (MPS)"   # default macOS wheel already includes MPS
fi
ok "Accelerator detected: $ACCEL"

# ── 3. Backend: venv + dependencies ───────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  bold "[backend] Creating virtual environment…"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

bold "[backend] Installing Python dependencies (this can take several minutes)…"
python -m pip install --upgrade pip >/dev/null
if [ -n "$TORCH_INDEX" ]; then
  echo "    using PyTorch build: $TORCH_INDEX"
  pip install -r "$BACKEND/requirements.txt" --extra-index-url "$TORCH_INDEX"
else
  pip install -r "$BACKEND/requirements.txt"
fi
ok "Backend dependencies installed"

# ── 4. Frontend: install + build ──────────────────────────────────────────────
bold "[frontend] Installing UI packages…"
( cd "$FRONTEND" && (npm ci 2>/dev/null || npm install) )
ok "Frontend dependencies installed"

# ── 5. One-click optimisation → backend/.env ──────────────────────────────────
bold "[optimize] Tuning settings to your hardware…"
python "$ROOT/scripts/optimize.py"

echo
ok "Installation complete."
bold "Next step:  ./start.sh"
echo "   (Optional) Install Ollama from https://ollama.com for the local chat agents."
