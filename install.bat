@echo off
REM ============================================================
REM  AI Studio - Script d'installation pour Windows
REM  Adapte a une config NVIDIA RTX (CUDA 12.1).
REM  A lancer une seule fois, depuis une machine "vierge".
REM ============================================================
setlocal enabledelayedexpansion

REM Se placer dans le dossier du script
cd /d "%~dp0"
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

echo === AI Studio - Installation ===
echo.

REM ------------------------------------------------------------
REM  1) Python 3.11+
REM ------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo [setup] Python introuvable. Installation via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo ERREUR: winget n'est pas disponible.
    echo Installe Python 3.11+ manuellement depuis https://www.python.org/downloads/
    echo  ^(coche "Add python.exe to PATH"^) puis relance install.bat.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
  echo.
  echo [setup] Python installe. FERME puis ROUVRE ce terminal et relance install.bat
  echo         pour que le PATH soit mis a jour.
  pause
  exit /b 0
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [backend] Python !PYVER! detecte.

REM ------------------------------------------------------------
REM  2) Node.js 20+
REM ------------------------------------------------------------
where node >nul 2>&1
if errorlevel 1 (
  echo [setup] Node.js introuvable. Installation via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo ERREUR: winget n'est pas disponible.
    echo Installe Node.js 20+ manuellement depuis https://nodejs.org/ puis relance install.bat.
    pause
    exit /b 1
  )
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  echo.
  echo [setup] Node.js installe. FERME puis ROUVRE ce terminal et relance install.bat
  echo         pour que le PATH soit mis a jour.
  pause
  exit /b 0
)

for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
echo [frontend] Node !NODEVER! detecte.
echo.

REM ------------------------------------------------------------
REM  3) Environnement virtuel + dependances backend (CUDA 12.1)
REM ------------------------------------------------------------
if not exist "%BACKEND%\.venv" (
  echo [backend] Creation de l'environnement virtuel...
  python -m venv "%BACKEND%\.venv"
  if errorlevel 1 (
    echo ERREUR: impossible de creer le venv.
    pause
    exit /b 1
  )
)

echo [backend] Installation des dependances ^(torch CUDA 12.1 pour ta RTX, ca peut etre long^)...
call "%BACKEND%\.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r "%BACKEND%\requirements.txt" --extra-index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 (
  echo ERREUR: l'installation des dependances Python a echoue.
  pause
  exit /b 1
)

REM Fichier .env (depuis l'exemple) si absent
if not exist "%BACKEND%\.env" (
  if exist "%BACKEND%\.env.example" (
    copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
    echo [backend] Fichier .env cree depuis .env.example.
  )
)
echo.

REM ------------------------------------------------------------
REM  4) Dependances frontend
REM ------------------------------------------------------------
echo [frontend] Installation des paquets npm...
pushd "%FRONTEND%"
call npm install
if errorlevel 1 (
  echo ERREUR: npm install a echoue.
  popd
  pause
  exit /b 1
)
popd
echo.

echo ============================================================
echo  Installation terminee !
echo  Lance "start.bat" pour demarrer AI Studio.
echo.
echo  Optionnel: installe Ollama ^(https://ollama.com^) pour l'onglet Agent.
echo ============================================================
pause
endlocal
