#!/usr/bin/env bash
# AI Studio — one-command launcher (Linux, macOS, WSL, Git Bash on Windows).
#
#   ./start.sh                 dev mode: backend (auto-reload) + Vite dev server
#   MODE=prod ./start.sh       builds the UI once, everything served on one port
#
# Options (environment variables):
#   BACKEND_PORT=8000  FRONTEND_PORT=5173  NO_BROWSER=1  TORCH_VARIANT=cuda|cpu|default
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
MODE="${MODE:-dev}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export BACKEND_PORT FRONTEND_PORT

say()  { printf '\033[1;35m[ai-studio]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

hash_of() {  # portable content hash of the given files
  if command -v sha256sum >/dev/null 2>&1; then cat "$@" | sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then cat "$@" | shasum -a 256 | cut -d' ' -f1
  else cat "$@" | cksum | cut -d' ' -f1; fi
}

echo "=== AI Studio ($MODE) ==="

# ── Python: the ML stack (torch 2.4) supports Python 3.10 – 3.12 ───────────────
PYTHON=""
for cand in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then
    PYTHON="$cand"; break
  fi
done
[ -n "$PYTHON" ] || die "Python 3.10, 3.11 or 3.12 is required (PyTorch has no wheels for other versions).
       Install one from https://www.python.org/downloads/ (or: brew install python@3.12 / apt install python3.12-venv)."

command -v node >/dev/null 2>&1 || die "Node.js 18+ is required: https://nodejs.org"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || die "Node.js 18+ is required (found $(node -v))."

# ── Backend environment ───────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  say "Creating Python virtual environment ($("$PYTHON" --version))..."
  "$PYTHON" -m venv "$VENV" || die "venv creation failed (on Debian/Ubuntu: apt install python3-venv)."
fi
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
else
  # shellcheck disable=SC1091
  source "$VENV/Scripts/activate"   # Git Bash on Windows
fi

# Pick the PyTorch build that matches this machine.
OS="$(uname -s)"
VARIANT="${TORCH_VARIANT:-}"
if [ -z "$VARIANT" ]; then
  if [ "$OS" = "Darwin" ]; then VARIANT="default"
  elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then VARIANT="cuda"
  else VARIANT="cpu"; fi
fi

REQ="$BACKEND/requirements.txt"
STAMP="$VENV/.requirements-$VARIANT.sha"
WANT="$(hash_of "$REQ")"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  say "Installing backend dependencies (PyTorch: $VARIANT) — the first run takes a while..."
  python -m pip install --upgrade pip >/dev/null
  case "$VARIANT" in
    cuda)
      python -m pip install -r "$REQ" --extra-index-url https://download.pytorch.org/whl/cu121 ;;
    cpu)
      # CPU-only: smaller torch wheels, and skip GPU-only packages.
      TMP_REQ="$(mktemp)"
      sed -e '/^xformers/d' -e 's/^onnxruntime-gpu==\([^;]*\);.*/onnxruntime==\1/' \
          -e '/^onnxruntime==.*darwin/d' "$REQ" > "$TMP_REQ"
      python -m pip install -r "$TMP_REQ" --extra-index-url https://download.pytorch.org/whl/cpu
      rm -f "$TMP_REQ" ;;
    *)
      python -m pip install -r "$REQ" ;;
  esac
  echo "$WANT" > "$STAMP"   # only written when the install succeeded
fi

if [ ! -f "$BACKEND/.env" ] && [ -f "$BACKEND/.env.example" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  say "Created backend/.env from the example (edit it to add tokens)."
fi

# ── Frontend environment ──────────────────────────────────────────────────────
NPM_STAMP="$FRONTEND/node_modules/.lock.sha"
NPM_WANT="$(hash_of "$FRONTEND/package-lock.json")"
if [ ! -d "$FRONTEND/node_modules" ] || [ ! -f "$NPM_STAMP" ] || [ "$(cat "$NPM_STAMP")" != "$NPM_WANT" ]; then
  say "Installing frontend packages..."
  (cd "$FRONTEND" && npm ci --no-audit --no-fund) || (cd "$FRONTEND" && npm install --no-audit --no-fund)
  echo "$NPM_WANT" > "$NPM_STAMP"
fi

# ── Optional services ─────────────────────────────────────────────────────────
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
if command -v curl >/dev/null 2>&1 && ! curl -sf --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  warn "Ollama not reachable at $OLLAMA_URL — the Agent tab needs it (https://ollama.com, then: ollama pull llama3.2)."
fi

port_busy() {
  if command -v lsof >/dev/null 2>&1; then lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; fi
}
port_busy "$BACKEND_PORT" && die "Port $BACKEND_PORT is already in use (set BACKEND_PORT=...)."

# ── Launch ────────────────────────────────────────────────────────────────────
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  say "Stopping..."
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "$MODE" = "prod" ]; then
  say "Building the UI..."
  (cd "$FRONTEND" && npm run build)
  URL="http://localhost:$BACKEND_PORT"
  (cd "$BACKEND" && exec python -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT") &
  PIDS+=($!)
else
  port_busy "$FRONTEND_PORT" && die "Port $FRONTEND_PORT is already in use (set FRONTEND_PORT=...)."
  URL="http://localhost:$FRONTEND_PORT"
  (cd "$BACKEND" && exec python -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
      --reload --reload-dir "$BACKEND" --reload-exclude .venv) &
  PIDS+=($!)
  (cd "$FRONTEND" && exec node node_modules/vite/bin/vite.js --port "$FRONTEND_PORT" --strictPort) &
  PIDS+=($!)
fi

# Wait for the API, then open the browser.
for _ in $(seq 1 120); do
  if command -v curl >/dev/null 2>&1; then
    curl -sf --max-time 1 "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1 && break
  else
    sleep 3; break
  fi
  sleep 0.5
done

echo ""
say "Ready → $URL   (API docs: http://localhost:$BACKEND_PORT/docs)"
say "Press Ctrl+C to stop."
echo ""
if [ -z "${NO_BROWSER:-}" ] && [ -z "${SSH_CONNECTION:-}" ]; then
  if [ "$OS" = "Darwin" ]; then open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$URL" >/dev/null 2>&1 || true
  fi
fi

# Exit (and stop the other server) as soon as either one stops.
wait -n 2>/dev/null || wait
