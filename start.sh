#!/usr/bin/env bash
# AI Studio — startup script
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "=== AI Studio ==="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found"
  exit 1
fi

# Check Node
if ! command -v node &>/dev/null; then
  echo "ERROR: node not found"
  exit 1
fi

# Install backend deps if needed
if [ ! -d "$BACKEND/.venv" ]; then
  echo "[backend] Creating virtual environment..."
  python3 -m venv "$BACKEND/.venv"
  source "$BACKEND/.venv/bin/activate"
  echo "[backend] Installing dependencies (this may take a while)..."
  pip install --upgrade pip
  pip install -r "$BACKEND/requirements.txt" \
    --extra-index-url https://download.pytorch.org/whl/cu121
else
  source "$BACKEND/.venv/bin/activate"
fi

# Install frontend deps if needed
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "[frontend] Installing npm packages..."
  cd "$FRONTEND" && npm install && cd "$ROOT"
fi

# First-run hardware optimisation (writes backend/.env).
if [ ! -f "$BACKEND/.env" ]; then
  echo "[optimize] First run — tuning to your hardware..."
  python "$ROOT/scripts/optimize.py" || true
fi

echo ""
echo "[backend]  Starting FastAPI on http://localhost:8000"
echo "[frontend] Starting Vite on  http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both servers."
echo ""

# Start backend
cd "$BACKEND"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend
cd "$FRONTEND"
npm run dev &
FRONTEND_PID=$!

# Wait and cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM
wait $BACKEND_PID $FRONTEND_PID
