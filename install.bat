@echo off
REM AI Studio - one-click installer (Windows)
REM Beginners: double-click this file, or run it from a terminal in this folder.
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === AI Studio installer ===
echo.

REM --- 1. Python ---------------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [X] Python not found. Install Python 3.10+ from https://python.org
  echo     IMPORTANT: tick "Add python.exe to PATH" during setup, then re-run.
  pause & exit /b 1
)
%PY% -c "import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)" || (
  echo [X] Python is too old; need 3.10 or newer. & pause & exit /b 1
)
echo [OK] Python found.

REM --- 2. Node.js --------------------------------------------------------------
where node >nul 2>nul || (
  echo [X] Node.js not found. Install the LTS from https://nodejs.org and re-run.
  pause & exit /b 1
)
echo [OK] Node.js found.

REM --- 3. Detect NVIDIA GPU -> PyTorch build -----------------------------------
set "TORCH_INDEX="
set "ACCEL=CPU"
where nvidia-smi >nul 2>nul && (
  set "ACCEL=NVIDIA CUDA"
  set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
)
echo [OK] Accelerator detected: !ACCEL!

REM --- 4. Backend venv + deps --------------------------------------------------
if not exist "backend\.venv" (
  echo [backend] Creating virtual environment...
  %PY% -m venv "backend\.venv"
)
call "backend\.venv\Scripts\activate.bat"

echo [backend] Installing Python dependencies (this can take several minutes)...
python -m pip install --upgrade pip >nul
if defined TORCH_INDEX (
  echo     using PyTorch build: !TORCH_INDEX!
  pip install -r "backend\requirements.txt" --extra-index-url !TORCH_INDEX! || ( echo [X] pip install failed & pause & exit /b 1 )
) else (
  pip install -r "backend\requirements.txt" || ( echo [X] pip install failed & pause & exit /b 1 )
)
echo [OK] Backend dependencies installed.

REM --- 5. Frontend -------------------------------------------------------------
echo [frontend] Installing UI packages...
pushd frontend
call npm ci || call npm install || ( echo [X] npm install failed & popd & pause & exit /b 1 )
popd
echo [OK] Frontend dependencies installed.

REM --- 6. One-click optimisation ----------------------------------------------
echo [optimize] Tuning settings to your hardware...
python "scripts\optimize.py"

echo.
echo [OK] Installation complete.
echo Next step:  start.bat
echo    (Optional) Install Ollama from https://ollama.com for the local chat agents.
pause
