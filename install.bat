@echo off
REM ============================================================
REM  AI Studio - Installation Windows (resiliente et autonome)
REM
REM  - Detecte ou installe Python 3.11/3.12, Node.js 20+, Ollama
REM  - Fallbacks : winget -> telechargement direct (curl, PowerShell, bitsadmin)
REM  - Rafraichit le PATH tout seul : pas besoin de fermer/rouvrir le terminal
REM  - Reessaie chaque etape, puis relance l'installation complete (3 passes)
REM  - Detecte le GPU NVIDIA ; repli automatique sur torch CPU sinon
REM  - Reexecutable a volonte : reprend la ou ca s'est arrete
REM  - Journal complet dans install.log
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "LOG=%ROOT%\install.log"
set "MARKER=%ROOT%\.install_ok"
set "DL_DIR=%TEMP%\ai-studio-setup"

REM Versions epinglees pour les telechargements directs (fallback sans winget)
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "NODE_VER=v20.18.1"
set "NODE_ZIP_URL=https://nodejs.org/dist/%NODE_VER%/node-%NODE_VER%-win-x64.zip"
set "OLLAMA_URL=https://ollama.com/download/OllamaSetup.exe"
set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"

> "%LOG%" echo [%date% %time%] === AI Studio - Installation ===
echo === AI Studio - Installation ===
echo     Journal detaille : %LOG%
echo.

call :check_disk

REM ------------------------------------------------------------
REM  Boucle globale : si une passe echoue, on relance tout (3x).
REM  Chaque etape est idempotente : rien n'est refait inutilement.
REM ------------------------------------------------------------
set /a GLOBAL_TRY=0
:global_retry
set /a GLOBAL_TRY+=1
call :log "--- Passe d'installation %GLOBAL_TRY%/3 ---"
call :main
if not errorlevel 1 goto :success
if %GLOBAL_TRY% geq 3 goto :failure
call :log "[retry] La passe %GLOBAL_TRY% a echoue. Relance complete dans 15 s..."
timeout /t 15 /nobreak >nul
call :refresh_path
goto :global_retry

:success
echo.
call :log "Installation terminee avec succes."
echo ============================================================
echo  Installation terminee !
echo  Lance "start.bat" pour demarrer AI Studio.
echo ============================================================
if not defined AI_STUDIO_NOPAUSE pause
endlocal
exit /b 0

:failure
echo.
call :log "ECHEC apres %GLOBAL_TRY% passes completes."
echo ============================================================
echo  L'installation n'a pas abouti apres %GLOBAL_TRY% tentatives.
echo   1. Verifie ta connexion internet puis relance install.bat :
echo      le script reprendra la ou il s'est arrete.
echo   2. En cas de probleme persistant, consulte le journal :
echo      %LOG%
echo ============================================================
if not defined AI_STUDIO_NOPAUSE pause
endlocal
exit /b 1

REM ============================================================
REM  Sequence principale d'une passe d'installation
REM ============================================================
:main
call :log "[etape 1/6] Verification de la connexion reseau..."
call :wait_network

call :log "[etape 2/6] Python 3.11/3.12..."
call :ensure_python
if errorlevel 1 exit /b 1

call :log "[etape 3/6] Node.js 20+..."
call :ensure_node
if errorlevel 1 exit /b 1

call :log "[etape 4/6] Environnement virtuel + dependances backend..."
call :setup_backend
if errorlevel 1 exit /b 1

call :log "[etape 5/6] Dependances frontend (npm)..."
call :setup_frontend
if errorlevel 1 exit /b 1

call :log "[etape 6/6] Ollama + modele agent (optionnel, jamais bloquant)..."
call :setup_ollama

call :verify_install
if errorlevel 1 exit /b 1
exit /b 0

REM ============================================================
REM  Outils generiques
REM ============================================================

REM --- Ecrit sur la console ET dans install.log ---
:log
echo %~1
>> "%LOG%" echo [%date% %time%] %~1
exit /b 0

REM --- Avertit si le disque risque d'etre trop petit (non bloquant) ---
:check_disk
set "FREE_GB="
for /f %%a in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive -Name (Get-Location).Drive.Name).Free / 1GB)" 2^>nul') do set "FREE_GB=%%a"
if defined FREE_GB (
  call :log "[disque] Espace libre : %FREE_GB% Go."
  if %FREE_GB% LSS 15 (
    call :log "[attention] Moins de 15 Go libres : torch CUDA + les modeles ont besoin de place."
    call :log "            Le script continue quand meme, mais libere de l'espace si possible."
  )
)
exit /b 0

REM --- Attend le reseau (6 essais), puis continue quoi qu'il arrive ---
:wait_network
set /a NET_TRY=0
:wait_network_loop
curl -s -m 8 -o nul https://pypi.org/simple/ 2>nul && exit /b 0
ping -n 1 -w 3000 8.8.8.8 >nul 2>&1 && exit /b 0
set /a NET_TRY+=1
if %NET_TRY% geq 6 (
  call :log "[reseau] Pas de connexion detectee : on continue quand meme (caches locaux possibles)."
  exit /b 0
)
call :log "[reseau] Pas de connexion (essai %NET_TRY%/6). Nouvel essai dans 10 s..."
timeout /t 10 /nobreak >nul
goto :wait_network_loop

REM --- Recharge le PATH depuis le registre (installations recentes) ---
REM     + ajoute les emplacements standards de Python / Node / Ollama.
:refresh_path
set "SYSPATH="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')" 2^>nul`) do set "SYSPATH=%%p"
if not defined SYSPATH set "SYSPATH=%PATH%"
set "PATH=%SYSPATH%;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%LocalAppData%\Programs\Python\Launcher;%ProgramFiles%\nodejs;%LocalAppData%\Programs\nodejs;%LocalAppData%\Programs\Ollama;%windir%;%windir%\System32"
exit /b 0

REM --- Telechargement robuste : curl (3 essais) -> PowerShell -> bitsadmin ---
REM     %1 = URL, %2 = fichier destination. Retourne 1 si tout echoue.
:download
set "DL_URL=%~1"
set "DL_DEST=%~2"
if not exist "%DL_DIR%" mkdir "%DL_DIR%" >nul 2>&1
del /q "%DL_DEST%" >nul 2>&1
set /a DL_TRY=0
:download_loop
set /a DL_TRY+=1
call :log "[download] %DL_URL% (essai %DL_TRY%/3)"
curl -L --fail --connect-timeout 20 --retry 2 -o "%DL_DEST%" "%DL_URL%"
if not errorlevel 1 if exist "%DL_DEST%" exit /b 0
if %DL_TRY% LSS 3 (
  timeout /t 5 /nobreak >nul
  goto :download_loop
)
call :log "[download] curl a echoue, essai via PowerShell..."
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%DL_URL%' -OutFile '%DL_DEST%' -UseBasicParsing } catch { exit 1 }"
if not errorlevel 1 if exist "%DL_DEST%" exit /b 0
call :log "[download] PowerShell a echoue, essai via bitsadmin..."
bitsadmin /transfer aistudio_dl /download /priority foreground "%DL_URL%" "%DL_DEST%" >nul 2>&1
if exist "%DL_DEST%" exit /b 0
call :log "[download] Echec du telechargement de %DL_URL%."
exit /b 1

REM ============================================================
REM  Etape 2 : Python 3.11/3.12 (torch cu121 n'existe pas en 3.13+)
REM ============================================================
:ensure_python
call :find_python
if defined PYCMD goto :python_ok
call :log "[python] Python 3.11/3.12 introuvable. Installation automatique..."
call :install_python
call :refresh_path
call :find_python
if defined PYCMD goto :python_ok
call :log "[python] ERREUR : Python 3.11/3.12 toujours introuvable apres installation."
call :log "         Installation manuelle : https://www.python.org/downloads/release/python-3119/"
exit /b 1
:python_ok
for /f "tokens=2" %%v in ('call %PYCMD% --version 2^>^&1') do set "PYVER=%%v"
call :log "[python] Version %PYVER% (commande : %PYCMD%)"
exit /b 0

REM --- Cherche un interpreteur compatible : lanceur py, PATH, dossiers standards ---
:find_python
set "PYCMD="
py -3.11 --version >nul 2>&1 && set "PYCMD=py -3.11"
if defined PYCMD exit /b 0
py -3.12 --version >nul 2>&1 && set "PYCMD=py -3.12"
if defined PYCMD exit /b 0
call :try_python python
if defined PYCMD exit /b 0
call :try_python python3
if defined PYCMD exit /b 0
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" call :try_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PYCMD exit /b 0
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" call :try_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PYCMD exit /b 0
if exist "%ProgramFiles%\Python311\python.exe" call :try_python "%ProgramFiles%\Python311\python.exe"
if defined PYCMD exit /b 0
if exist "%ProgramFiles%\Python312\python.exe" call :try_python "%ProgramFiles%\Python312\python.exe"
exit /b 0

REM --- Valide un candidat : ne retient que du 3.11 ou 3.12 fonctionnel ---
:try_python
set "PY_CAND=%~1"
set "PY_CAND_VER="
for /f "tokens=2" %%v in ('call "%PY_CAND%" --version 2^>^&1') do set "PY_CAND_VER=%%v"
if not defined PY_CAND_VER exit /b 0
for /f "tokens=1,2 delims=." %%a in ("%PY_CAND_VER%") do (
  if "%%a.%%b"=="3.11" set "PYCMD="%PY_CAND%""
  if "%%a.%%b"=="3.12" set "PYCMD="%PY_CAND%""
)
exit /b 0

REM --- Installe Python : winget, sinon installeur officiel en silencieux ---
:install_python
where winget >nul 2>&1
if not errorlevel 1 (
  call :log "[python] Tentative via winget..."
  winget install -e --id Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
  call :refresh_path
  call :find_python
  if defined PYCMD exit /b 0
  call :log "[python] winget n'a pas suffi. Telechargement direct depuis python.org..."
) else (
  call :log "[python] winget indisponible. Telechargement direct depuis python.org..."
)
call :download "%PY_URL%" "%DL_DIR%\python-setup.exe"
if errorlevel 1 exit /b 1
call :log "[python] Installation silencieuse (utilisateur courant, ajout au PATH)..."
start /wait "" "%DL_DIR%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
call :refresh_path
exit /b 0

REM ============================================================
REM  Etape 3 : Node.js 20+
REM ============================================================
:ensure_node
call :find_node
if defined NODEVER goto :node_ok
call :log "[node] Node.js introuvable. Installation automatique..."
where winget >nul 2>&1
if not errorlevel 1 (
  call :log "[node] Tentative via winget..."
  winget install -e --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
  call :refresh_path
  call :find_node
  if defined NODEVER goto :node_ok
  call :log "[node] winget n'a pas suffi. Installation portable (zip, sans droits admin)..."
) else (
  call :log "[node] winget indisponible. Installation portable (zip, sans droits admin)..."
)
call :download "%NODE_ZIP_URL%" "%DL_DIR%\node.zip"
if errorlevel 1 exit /b 1
call :log "[node] Extraction vers %LocalAppData%\Programs\nodejs..."
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Expand-Archive -Path '%DL_DIR%\node.zip' -DestinationPath '%DL_DIR%\node' -Force"
if errorlevel 1 exit /b 1
if not exist "%LocalAppData%\Programs" mkdir "%LocalAppData%\Programs" >nul 2>&1
rmdir /s /q "%LocalAppData%\Programs\nodejs" >nul 2>&1
move "%DL_DIR%\node\node-%NODE_VER%-win-x64" "%LocalAppData%\Programs\nodejs" >nul
if errorlevel 1 exit /b 1
set "PATH=%LocalAppData%\Programs\nodejs;%PATH%"
REM Rendre node disponible aussi dans les futurs terminaux (PATH utilisateur)
powershell -NoProfile -Command "$u=[Environment]::GetEnvironmentVariable('Path','User'); $d='%LocalAppData%\Programs\nodejs'; if ($u -notlike ('*'+$d+'*')) { [Environment]::SetEnvironmentVariable('Path', ($u.TrimEnd(';')+';'+$d), 'User') }" >nul 2>&1
call :find_node
if defined NODEVER goto :node_ok
call :log "[node] ERREUR : Node.js toujours introuvable apres installation."
call :log "       Installation manuelle : https://nodejs.org/"
exit /b 1
:node_ok
call :log "[node] Version %NODEVER% detectee."
exit /b 0

REM --- Cherche node : PATH puis dossiers standards (ajoutes au PATH si besoin) ---
:find_node
set "NODEVER="
where node >nul 2>&1
if not errorlevel 1 (
  for /f "tokens=*" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
  exit /b 0
)
for %%d in ("%ProgramFiles%\nodejs" "%LocalAppData%\Programs\nodejs") do (
  if not defined NODEVER if exist "%%~d\node.exe" (
    set "PATH=%%~d;!PATH!"
    for /f "tokens=*" %%v in ('"%%~d\node.exe" --version 2^>^&1') do set "NODEVER=%%v"
  )
)
exit /b 0

REM ============================================================
REM  Etape 4 : venv + dependances backend (CUDA si GPU NVIDIA, sinon CPU)
REM ============================================================
:setup_backend
set "VENVDIR=%BACKEND%\.venv"
set "VPY=%VENVDIR%\Scripts\python.exe"

REM venv incomplet (installation interrompue) : on repart de zero
if exist "%VENVDIR%" if not exist "%VPY%" (
  call :log "[backend] venv incomplet detecte : suppression..."
  rmdir /s /q "%VENVDIR%" >nul 2>&1
)

REM venv existant : verifier version Python et bon fonctionnement
if exist "%VPY%" (
  set "VENV_OK="
  for /f "tokens=2" %%v in ('call "%VPY%" --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ("%%v") do (
      if "%%a.%%b"=="3.11" set "VENV_OK=1"
      if "%%a.%%b"=="3.12" set "VENV_OK=1"
    )
  )
  if defined VENV_OK (
    "%VPY%" -c "import sys" >nul 2>&1
    if errorlevel 1 set "VENV_OK="
  )
  if not defined VENV_OK (
    call :log "[backend] venv existant invalide ou en mauvaise version : recreation..."
    rmdir /s /q "%VENVDIR%" >nul 2>&1
  )
)

if not exist "%VENVDIR%" (
  call :log "[backend] Creation de l'environnement virtuel..."
  %PYCMD% -m venv "%VENVDIR%"
)
if not exist "%VPY%" (
  call :log "[backend] Premier essai rate : nettoyage puis nouvelle tentative..."
  rmdir /s /q "%VENVDIR%" >nul 2>&1
  %PYCMD% -m venv "%VENVDIR%"
)
if not exist "%VPY%" (
  call :log "[backend] ERREUR : impossible de creer l'environnement virtuel."
  exit /b 1
)

call :log "[backend] Mise a jour de pip..."
"%VPY%" -m pip install --upgrade pip --timeout 60 --retries 5 >nul 2>&1
if errorlevel 1 call :log "[backend] (mise a jour de pip echouee : on continue avec la version actuelle)"

call :detect_gpu
if "%HAS_NVIDIA%"=="1" (
  call :log "[backend] GPU NVIDIA detecte : torch CUDA 12.1 sera installe."
) else (
  call :log "[backend] Aucun GPU NVIDIA detecte : torch CPU sera installe (pas d'acceleration)."
)

REM xformers est installe a part (wheel uniquement, jamais compile).
REM Variante CPU : torch/torchvision sans +cu121, onnxruntime sans -gpu.
set "REQ_GPU=%BACKEND%\requirements.win-gpu.tmp"
set "REQ_CPU=%BACKEND%\requirements.win-cpu.tmp"
findstr /v /i /c:"xformers" "%BACKEND%\requirements.txt" > "%REQ_GPU%"
powershell -NoProfile -Command "(Get-Content '%REQ_GPU%') -replace '\+cu121','' -replace 'onnxruntime-gpu','onnxruntime' | Set-Content '%REQ_CPU%'"

set "PIP_OK="
if "%HAS_NVIDIA%"=="1" (
  call :pip_attempts "%REQ_GPU%" "--extra-index-url %TORCH_INDEX%"
  if not errorlevel 1 set "PIP_OK=1"
  if not defined PIP_OK (
    call :log "[backend] Installation CUDA impossible apres 3 essais."
    call :log "[backend] Repli sur la version CPU pour ne pas bloquer (relance install.bat plus tard pour retenter en CUDA)."
    call :pip_attempts "%REQ_CPU%" ""
    if not errorlevel 1 set "PIP_OK=1"
  )
) else (
  call :pip_attempts "%REQ_CPU%" ""
  if not errorlevel 1 set "PIP_OK=1"
)
del /q "%REQ_GPU%" "%REQ_CPU%" >nul 2>&1
if not defined PIP_OK (
  call :log "[backend] ERREUR : les dependances Python n'ont pas pu etre installees."
  exit /b 1
)

if "%HAS_NVIDIA%"=="1" (
  call :log "[backend] xformers (optionnel, wheel uniquement, jamais compile)..."
  "%VPY%" -m pip install --only-binary=:all: xformers==0.0.28.post1 --extra-index-url %TORCH_INDEX% --timeout 60 --retries 3
  if errorlevel 1 call :log "[backend] Pas de wheel xformers pour cette config : PyTorch utilisera son attention SDPA."
)

if not exist "%BACKEND%\.env" if exist "%BACKEND%\.env.example" (
  copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
  call :log "[backend] Fichier .env cree depuis .env.example."
)
exit /b 0

REM --- pip install avec 3 essais, purge du cache a partir du 2e echec ---
:pip_attempts
set "REQ_FILE=%~1"
set "PIP_EXTRA=%~2"
set /a PIP_TRY=0
:pip_attempts_loop
set /a PIP_TRY+=1
call :log "[backend] pip install (essai %PIP_TRY%/3, plusieurs Go a telecharger : c'est long)..."
"%VPY%" -m pip install -r "%REQ_FILE%" %PIP_EXTRA% --timeout 60 --retries 5
if not errorlevel 1 exit /b 0
call :log "[backend] Echec de pip (essai %PIP_TRY%/3)."
if %PIP_TRY% geq 3 exit /b 1
if %PIP_TRY% geq 2 (
  call :log "[backend] Purge du cache pip (wheel possiblement corrompu)..."
  "%VPY%" -m pip cache purge >nul 2>&1
)
call :log "[backend] Nouvel essai dans 10 s..."
timeout /t 10 /nobreak >nul
goto :pip_attempts_loop

REM --- HAS_NVIDIA=1 si un GPU NVIDIA est present ---
:detect_gpu
set "HAS_NVIDIA=0"
nvidia-smi >nul 2>&1
if not errorlevel 1 set "HAS_NVIDIA=1"
if "%HAS_NVIDIA%"=="0" if exist "%windir%\System32\nvidia-smi.exe" set "HAS_NVIDIA=1"
if "%HAS_NVIDIA%"=="0" (
  powershell -NoProfile -Command "if (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'NVIDIA' }) { exit 0 } else { exit 1 }" >nul 2>&1
  if not errorlevel 1 set "HAS_NVIDIA=1"
)
exit /b 0

REM ============================================================
REM  Etape 5 : dependances frontend (npm), 4 essais avec nettoyage
REM ============================================================
:setup_frontend
if not exist "%FRONTEND%\package.json" (
  call :log "[frontend] ERREUR : %FRONTEND%\package.json introuvable."
  exit /b 1
)
set /a NPM_TRY=0
:npm_loop
set /a NPM_TRY+=1
set "NPM_CMD=install"
if exist "%FRONTEND%\package-lock.json" if %NPM_TRY% LEQ 2 set "NPM_CMD=ci"
call :log "[frontend] npm %NPM_CMD% (essai %NPM_TRY%/4)..."
pushd "%FRONTEND%"
call npm %NPM_CMD% --no-audit --no-fund
set "NPM_RC=%errorlevel%"
popd
if "%NPM_RC%"=="0" exit /b 0
call :log "[frontend] Echec de npm (essai %NPM_TRY%/4)."
if %NPM_TRY% geq 4 (
  call :log "[frontend] ERREUR : les dependances npm n'ont pas pu etre installees."
  exit /b 1
)
call :log "[frontend] Nettoyage (cache npm + node_modules) puis nouvel essai dans 10 s..."
call npm cache clean --force >nul 2>&1
rmdir /s /q "%FRONTEND%\node_modules" >nul 2>&1
timeout /t 10 /nobreak >nul
goto :npm_loop

REM ============================================================
REM  Etape 6 : Ollama (onglet Agent) - 100%% optionnel, jamais bloquant
REM ============================================================
:setup_ollama
set "OLLAMA_FOUND="
where ollama >nul 2>&1
if not errorlevel 1 set "OLLAMA_FOUND=1"
if not defined OLLAMA_FOUND if exist "%LocalAppData%\Programs\Ollama\ollama.exe" (
  set "PATH=%LocalAppData%\Programs\Ollama;!PATH!"
  set "OLLAMA_FOUND=1"
)
if defined OLLAMA_FOUND goto :ollama_present

call :log "[ollama] Ollama introuvable. Installation automatique (optionnelle)..."
where winget >nul 2>&1
if not errorlevel 1 (
  winget install -e --id Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements
  call :refresh_path
  where ollama >nul 2>&1 && set "OLLAMA_FOUND=1"
)
if defined OLLAMA_FOUND goto :ollama_present

call :download "%OLLAMA_URL%" "%DL_DIR%\OllamaSetup.exe"
if not errorlevel 1 (
  call :log "[ollama] Installation silencieuse..."
  start /wait "" "%DL_DIR%\OllamaSetup.exe" /VERYSILENT /NORESTART
  call :refresh_path
  where ollama >nul 2>&1 && set "OLLAMA_FOUND=1"
  if not defined OLLAMA_FOUND if exist "%LocalAppData%\Programs\Ollama\ollama.exe" (
    set "PATH=%LocalAppData%\Programs\Ollama;!PATH!"
    set "OLLAMA_FOUND=1"
  )
)
if defined OLLAMA_FOUND goto :ollama_present
call :log "[ollama] Installation impossible : l'onglet Agent restera indisponible (NON bloquant)."
call :log "         Installation manuelle possible plus tard : https://ollama.com"
exit /b 0

:ollama_present
call :log "[ollama] Ollama disponible."
if "%OLLAMA_BASE_URL%"=="" set "OLLAMA_BASE_URL=http://localhost:11434"
curl -s -m 5 -o nul "%OLLAMA_BASE_URL%/api/tags" 2>nul
if errorlevel 1 (
  call :log "[ollama] Demarrage du serveur Ollama en arriere-plan..."
  start "Ollama" /min cmd /c "ollama serve"
)
set /a OLLAMA_WAIT=0
:ollama_wait_loop
curl -s -m 5 -o nul "%OLLAMA_BASE_URL%/api/tags" 2>nul && goto :ollama_ready
set /a OLLAMA_WAIT+=1
if %OLLAMA_WAIT% geq 15 (
  call :log "[ollama] Serveur injoignable : le modele sera telecharge au prochain lancement (NON bloquant)."
  exit /b 0
)
timeout /t 2 /nobreak >nul
goto :ollama_wait_loop

:ollama_ready
ollama list 2>nul | findstr /i "llama3.2" >nul 2>&1
if not errorlevel 1 (
  call :log "[ollama] Modele llama3.2 deja present."
  exit /b 0
)
set /a PULL_TRY=0
:ollama_pull_loop
set /a PULL_TRY+=1
call :log "[ollama] Telechargement du modele llama3.2 (essai %PULL_TRY%/3, peut etre long)..."
ollama pull llama3.2
if not errorlevel 1 (
  call :log "[ollama] Modele pret."
  exit /b 0
)
if %PULL_TRY% geq 3 (
  call :log "[ollama] Echec du telechargement du modele (NON bloquant)."
  call :log "         A retenter plus tard : ollama pull llama3.2"
  exit /b 0
)
timeout /t 10 /nobreak >nul
goto :ollama_pull_loop

REM ============================================================
REM  Verification finale : tout doit reellement fonctionner
REM ============================================================
:verify_install
call :log "[verif] Controle final de l'installation..."
"%VPY%" -c "import fastapi, uvicorn, sqlalchemy, torch" >nul 2>&1
if errorlevel 1 (
  call :log "[verif] ERREUR : les dependances backend ne s'importent pas correctement."
  exit /b 1
)
if not exist "%FRONTEND%\node_modules" (
  call :log "[verif] ERREUR : node_modules manquant cote frontend."
  exit /b 1
)
> "%MARKER%" echo Installation OK le %date% %time%
call :log "[verif] Tout est en place."
exit /b 0
