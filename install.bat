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
REM  0) Pilote NVIDIA (necessaire pour utiliser la carte RTX)
REM ------------------------------------------------------------
where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo [warn] "nvidia-smi" introuvable : le pilote NVIDIA ne semble pas installe.
  echo        Sans pilote, la generation d'images utilisera le CPU ^(tres lent^).
  echo        Installe le dernier pilote GeForce depuis https://www.nvidia.com/drivers
  echo        puis relance install.bat. On continue quand meme...
  echo.
) else (
  for /f "tokens=*" %%g in ('nvidia-smi --query-gpu^=name --format^=csv^,noheader 2^>nul') do (
    echo [gpu] Carte detectee : %%g
  )
)
echo.

REM ------------------------------------------------------------
REM  1) Python 3.11 ou 3.12 (torch 2.4.1+cu121 n'existe PAS pour 3.13+)
REM ------------------------------------------------------------
REM  On cherche un interpreteur COMPATIBLE via le lanceur "py".
REM  PYCMD contiendra la commande a utiliser pour creer le venv.
set "PYCMD="
py -3.11 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3.11"
if not defined PYCMD (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -3.12"
)

REM  Repli: un "python" sur le PATH dont la version majeure.mineure est 3.11 ou 3.12
if not defined PYCMD (
  for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
  for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    if "%%a.%%b"=="3.11" set "PYCMD=python"
    if "%%a.%%b"=="3.12" set "PYCMD=python"
  )
)

if not defined PYCMD (
  echo [setup] Aucun Python 3.11/3.12 compatible trouve ^(torch CUDA ne supporte pas 3.13+^).
  echo [setup] Installation de Python 3.11 via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo ERREUR: winget n'est pas disponible.
    echo Installe Python 3.11 manuellement depuis https://www.python.org/downloads/release/python-3119/
    echo  ^(coche "Add python.exe to PATH"^) puis relance install.bat.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
  echo.
  echo [setup] Python 3.11 installe. FERME puis ROUVRE ce terminal et relance install.bat.
  pause
  exit /b 0
)

for /f "tokens=2" %%v in ('%PYCMD% --version 2^>^&1') do set "PYVER=%%v"
echo [backend] Python !PYVER! utilise pour le venv ^(commande: %PYCMD%^).

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
REM  Si un venv existe deja, verifier qu'il est en 3.11/3.12 ; sinon le recreer.
if exist "%BACKEND%\.venv\Scripts\python.exe" (
  set "VENV_OK="
  for /f "tokens=2" %%v in ('"%BACKEND%\.venv\Scripts\python.exe" --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ("%%v") do (
      if "%%a.%%b"=="3.11" set "VENV_OK=1"
      if "%%a.%%b"=="3.12" set "VENV_OK=1"
    )
  )
  if not defined VENV_OK (
    echo [backend] venv existant incompatible ^(mauvaise version Python^) : recreation...
    rmdir /s /q "%BACKEND%\.venv"
  )
)

if not exist "%BACKEND%\.venv" (
  echo [backend] Creation de l'environnement virtuel avec %PYCMD%...
  %PYCMD% -m venv "%BACKEND%\.venv"
  if errorlevel 1 (
    echo ERREUR: impossible de creer le venv.
    pause
    exit /b 1
  )
)

echo [backend] Installation des dependances ^(torch CUDA 12.1 pour ta RTX, ca peut etre long^)...
call "%BACKEND%\.venv\Scripts\activate.bat"
python -m pip install --upgrade pip

REM  xformers n'a pas toujours de wheel Windows et ne doit PAS etre compile depuis
REM  les sources (ca exige CUDA Toolkit + Visual Studio). Le code retombe tout seul
REM  sur l'attention native SDPA de PyTorch s'il est absent. On installe donc tout
REM  SAUF xformers, puis xformers en "best-effort" (wheel uniquement, jamais de build).
set "REQ_TMP=%BACKEND%\requirements.win.tmp"
findstr /v /i /c:"xformers" "%BACKEND%\requirements.txt" > "%REQ_TMP%"
pip install -r "%REQ_TMP%" --extra-index-url https://download.pytorch.org/whl/cu121
set "PIP_RC=%errorlevel%"
del "%REQ_TMP%" >nul 2>&1
if not "%PIP_RC%"=="0" (
  echo ERREUR: l'installation des dependances Python a echoue.
  pause
  exit /b 1
)

echo [backend] Tentative d'installation de xformers ^(optionnel, wheel uniquement^)...
pip install --only-binary=:all: xformers==0.0.28.post1 --extra-index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 (
  echo [warn] Pas de wheel xformers pour ta config : on continue sans.
  echo        PyTorch utilisera son attention native SDPA ^(deja rapide sur RTX^).
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

REM ------------------------------------------------------------
REM  5) Ollama (onglet Agent) + modele par defaut
REM ------------------------------------------------------------
where ollama >nul 2>&1
if errorlevel 1 (
  echo [ollama] Ollama introuvable. Installation via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo [warn] winget indisponible : installe Ollama manuellement depuis https://ollama.com
    echo        ^(l'onglet Agent restera indisponible jusque-la^).
    goto :after_ollama
  )
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  echo.
  echo [ollama] Ollama installe. Si la commande "ollama" n'est pas encore reconnue,
  echo          ferme/rouvre le terminal puis relance install.bat pour telecharger le modele.
) else (
  echo [ollama] Ollama deja installe.
)

REM Telecharger un modele par defaut pour l'agent (si ollama est utilisable)
where ollama >nul 2>&1
if not errorlevel 1 (
  echo [ollama] Telechargement du modele par defaut "llama3.2" ^(peut etre long^)...
  ollama pull llama3.2
  if errorlevel 1 (
    echo [warn] Echec du telechargement du modele. Tu pourras reessayer plus tard avec:
    echo        ollama pull llama3.2
  )
)
:after_ollama
echo.

echo ============================================================
echo  Installation terminee !
echo  Lance "start.bat" pour demarrer AI Studio.
echo ============================================================
pause
endlocal
