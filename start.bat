@echo off
REM AI Studio - start backend + frontend (Windows)
setlocal
cd /d "%~dp0"

if not exist "backend\.venv" (
  echo No virtual environment found. Run install.bat first.
  pause & exit /b 1
)
call "backend\.venv\Scripts\activate.bat"

if not exist "backend\.env" (
  echo [optimize] First run - tuning to your hardware...
  python "scripts\optimize.py"
)

echo.
echo [backend]  http://localhost:8000
echo [frontend] http://localhost:5173
echo Close this window to stop the servers.
echo.

pushd backend
start "AI Studio backend" cmd /c "call .venv\Scripts\activate.bat && uvicorn main:app --host 0.0.0.0 --port 8000"
popd

pushd frontend
start "AI Studio frontend" cmd /c "npm run dev"
popd

echo Servers launched in separate windows.
