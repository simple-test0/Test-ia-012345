@echo off
REM ============================================================
REM  AI Studio - Script de demarrage pour Windows
REM  Ouvre le backend (FastAPI) et le frontend (Vite) dans
REM  deux fenetres separees.
REM ============================================================
setlocal

cd /d "%~dp0"
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

echo === AI Studio ===
echo.

REM Verifier que l'installation a bien ete faite
if not exist "%BACKEND%\.venv" (
  echo ERREUR: environnement non installe.
  echo Lance d'abord "install.bat".
  pause
  exit /b 1
)
if not exist "%FRONTEND%\node_modules" (
  echo ERREUR: dependances frontend manquantes.
  echo Lance d'abord "install.bat".
  pause
  exit /b 1
)

REM Avertir si Ollama n'est pas joignable (onglet Agent)
if "%OLLAMA_BASE_URL%"=="" set "OLLAMA_BASE_URL=http://localhost:11434"
curl -sf "%OLLAMA_BASE_URL%/api/tags" >nul 2>&1
if errorlevel 1 (
  echo [warn] Ollama injoignable sur %OLLAMA_BASE_URL% - l'onglet Agent sera indisponible.
  echo        Installe/demarre-le depuis https://ollama.com ^(optionnel^).
  echo.
)

REM MODE=prod -> pas de rechargement auto
if /i "%MODE%"=="prod" (
  set "UVICORN_ARGS=--host 0.0.0.0 --port 8000"
) else (
  set "UVICORN_ARGS=--host 0.0.0.0 --port 8000 --reload"
)

echo [backend]  Demarrage de FastAPI  sur http://localhost:8000
echo [frontend] Demarrage de Vite     sur http://localhost:5173
echo.
echo Deux fenetres vont s'ouvrir. Ferme-les pour arreter les serveurs.
echo.

start "AI Studio - Backend" /d "%BACKEND%" cmd /k "call .venv\Scripts\activate.bat && uvicorn main:app %UVICORN_ARGS%"
start "AI Studio - Frontend" /d "%FRONTEND%" cmd /k "npm run dev"

REM Ouvrir le navigateur sur l'interface
timeout /t 4 /nobreak >nul
start "" http://localhost:5173

endlocal
