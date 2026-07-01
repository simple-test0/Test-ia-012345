@echo off
REM ============================================================
REM  AI Studio - Demarrage Windows (autonome et auto-reparant)
REM
REM  - Installe automatiquement ce qui manque (appelle install.bat)
REM  - Detecte les serveurs deja lances (pas de doublon)
REM  - Redemarre backend/frontend automatiquement s'ils plantent
REM  - Attend que le backend reponde avant d'ouvrir le navigateur
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "RUNDIR=%ROOT%\.run"

echo === AI Studio ===
echo.

REM ------------------------------------------------------------
REM  1) Auto-reparation : si l'installation manque ou est
REM     incomplete, on la (re)lance automatiquement.
REM ------------------------------------------------------------
set "NEED_INSTALL="
if not exist "%BACKEND%\.venv\Scripts\python.exe" set "NEED_INSTALL=1"
if not exist "%FRONTEND%\node_modules" set "NEED_INSTALL=1"
if defined NEED_INSTALL (
  echo [setup] Installation manquante ou incomplete : lancement automatique de install.bat...
  echo.
  set "AI_STUDIO_NOPAUSE=1"
  call "%ROOT%\install.bat"
  if errorlevel 1 (
    echo.
    echo ERREUR: l'installation automatique a echoue. Consulte install.log puis relance start.bat.
    pause
    exit /b 1
  )
  set "AI_STUDIO_NOPAUSE="
  echo.
)

REM ------------------------------------------------------------
REM  2) S'assurer que npm est utilisable dans CETTE session
REM     (cas d'une installation portable toute fraiche de Node)
REM ------------------------------------------------------------
where npm >nul 2>&1
if errorlevel 1 (
  for %%d in ("%ProgramFiles%\nodejs" "%LocalAppData%\Programs\nodejs") do (
    if exist "%%~d\npm.cmd" set "PATH=%%~d;!PATH!"
  )
)
where npm >nul 2>&1
if errorlevel 1 (
  echo ERREUR: npm introuvable. Relance install.bat ^(ou ouvre un nouveau terminal^).
  pause
  exit /b 1
)

REM ------------------------------------------------------------
REM  3) Ollama (onglet Agent, optionnel) : demarrer le serveur
REM     s'il est installe mais pas encore lance.
REM ------------------------------------------------------------
if "%OLLAMA_BASE_URL%"=="" set "OLLAMA_BASE_URL=http://localhost:11434"
where ollama >nul 2>&1
if errorlevel 1 if exist "%LocalAppData%\Programs\Ollama\ollama.exe" set "PATH=%LocalAppData%\Programs\Ollama;%PATH%"
curl -s -m 5 -o nul "%OLLAMA_BASE_URL%/api/tags" 2>nul
if errorlevel 1 (
  where ollama >nul 2>&1
  if not errorlevel 1 (
    echo [ollama] Demarrage du serveur Ollama en arriere-plan...
    start "Ollama" /min cmd /c "ollama serve"
  ) else (
    echo [warn] Ollama injoignable sur %OLLAMA_BASE_URL% - l'onglet Agent sera indisponible.
    echo        Relance install.bat ou installe-le depuis https://ollama.com ^(optionnel^).
  )
  echo.
)

REM MODE=prod -> pas de rechargement auto
if /i "%MODE%"=="prod" (
  set "UVICORN_ARGS=--host 0.0.0.0 --port 8000"
) else (
  set "UVICORN_ARGS=--host 0.0.0.0 --port 8000 --reload"
)

REM ------------------------------------------------------------
REM  4) Ne pas lancer de doublon si les serveurs tournent deja
REM ------------------------------------------------------------
set "BACKEND_UP="
curl -s -m 3 -o nul http://localhost:8000/health 2>nul && set "BACKEND_UP=1"
set "FRONTEND_UP="
curl -s -m 3 -o nul http://localhost:5173 2>nul && set "FRONTEND_UP=1"

REM ------------------------------------------------------------
REM  5) Scripts de supervision : chaque serveur est relance
REM     automatiquement 3 s apres un arret/crash.
REM ------------------------------------------------------------
if not exist "%RUNDIR%" mkdir "%RUNDIR%" >nul 2>&1

(
  echo @echo off
  echo title AI Studio - Backend
  echo cd /d "%BACKEND%"
  echo :loop
  echo .venv\Scripts\python.exe -m uvicorn main:app %UVICORN_ARGS%
  echo echo.
  echo echo [backend] Serveur arrete. Redemarrage dans 3 s... ^(ferme cette fenetre pour arreter^)
  echo timeout /t 3
  echo goto loop
) > "%RUNDIR%\backend_loop.bat"

(
  echo @echo off
  echo title AI Studio - Frontend
  echo cd /d "%FRONTEND%"
  echo :loop
  echo call npm run dev
  echo echo.
  echo echo [frontend] Serveur arrete. Redemarrage dans 3 s... ^(ferme cette fenetre pour arreter^)
  echo timeout /t 3
  echo goto loop
) > "%RUNDIR%\frontend_loop.bat"

if defined BACKEND_UP (
  echo [backend]  Deja en cours sur http://localhost:8000
) else (
  echo [backend]  Demarrage de FastAPI  sur http://localhost:8000
  start "AI Studio - Backend" cmd /c "%RUNDIR%\backend_loop.bat"
)
if defined FRONTEND_UP (
  echo [frontend] Deja en cours sur http://localhost:5173
) else (
  echo [frontend] Demarrage de Vite     sur http://localhost:5173
  start "AI Studio - Frontend" cmd /c "%RUNDIR%\frontend_loop.bat"
)
echo.
echo Les serveurs tournent dans deux fenetres et redemarrent seuls en cas de crash.
echo Ferme ces fenetres pour tout arreter.
echo.

REM ------------------------------------------------------------
REM  6) Attendre que le backend reponde, puis ouvrir le navigateur
REM ------------------------------------------------------------
if defined BACKEND_UP goto :backend_done
echo [backend]  Attente du demarrage...
set /a WAIT_B=0
:wait_backend
curl -s -m 3 -o nul http://localhost:8000/health 2>nul && goto :backend_ready
set /a WAIT_B+=1
if %WAIT_B% geq 90 (
  echo [warn] Le backend ne repond toujours pas apres 3 minutes.
  echo        Regarde la fenetre "AI Studio - Backend" pour les details
  echo        ^(il continuera de redemarrer tout seul en cas de crash^).
  goto :backend_done
)
timeout /t 2 /nobreak >nul
goto :wait_backend
:backend_ready
echo [backend]  Pret !
:backend_done

if defined FRONTEND_UP goto :frontend_done
set /a WAIT_F=0
:wait_frontend
curl -s -m 3 -o nul http://localhost:5173 2>nul && goto :frontend_done
set /a WAIT_F+=1
if %WAIT_F% geq 30 goto :frontend_done
timeout /t 2 /nobreak >nul
goto :wait_frontend
:frontend_done

start "" http://localhost:5173
echo Interface : http://localhost:5173
endlocal
