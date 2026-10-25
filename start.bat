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
REM Un arret via le bouton de l'interface laisse un stop.flag : on repart propre.
if exist "%RUNDIR%\stop.flag" del "%RUNDIR%\stop.flag" >nul 2>&1
REM Nouveaux logs a chaque session (les serveurs tournent en fenetres cachees).
if exist "%RUNDIR%\backend.log" del "%RUNDIR%\backend.log" >nul 2>&1
if exist "%RUNDIR%\frontend.log" del "%RUNDIR%\frontend.log" >nul 2>&1

(
  echo @echo off
  echo title AI Studio - Backend
  echo cd /d "%BACKEND%"
  echo :loop
  echo .venv\Scripts\python.exe -m uvicorn main:app %UVICORN_ARGS% ^>^> "%RUNDIR%\backend.log" 2^>^&1
  echo if exist "%RUNDIR%\stop.flag" exit
  echo echo [%%date%% %%time%%] [backend] serveur arrete, redemarrage dans 3 s ^>^> "%RUNDIR%\backend.log"
  echo timeout /t 3 /nobreak ^>nul
  echo if exist "%RUNDIR%\stop.flag" exit
  echo goto loop
) > "%RUNDIR%\backend_loop.bat"

(
  echo @echo off
  echo title AI Studio - Frontend
  echo cd /d "%FRONTEND%"
  echo :loop
  echo call npm run dev ^>^> "%RUNDIR%\frontend.log" 2^>^&1
  echo if exist "%RUNDIR%\stop.flag" exit
  echo echo [%%date%% %%time%%] [frontend] serveur arrete, redemarrage dans 3 s ^>^> "%RUNDIR%\frontend.log"
  echo timeout /t 3 /nobreak ^>nul
  echo if exist "%RUNDIR%\stop.flag" exit
  echo goto loop
) > "%RUNDIR%\frontend_loop.bat"

if defined BACKEND_UP (
  echo [backend]  Deja en cours sur http://localhost:8000
) else (
  echo [backend]  Demarrage de FastAPI  sur http://localhost:8000 ^(fenetre cachee^)
  powershell -NoProfile -Command "Start-Process -FilePath '%RUNDIR%\backend_loop.bat' -WindowStyle Hidden"
)
if defined FRONTEND_UP (
  echo [frontend] Deja en cours sur http://localhost:5173
) else (
  echo [frontend] Demarrage de Vite     sur http://localhost:5173 ^(fenetre cachee^)
  powershell -NoProfile -Command "Start-Process -FilePath '%RUNDIR%\frontend_loop.bat' -WindowStyle Hidden"
)
echo.
echo Les serveurs tournent en arriere-plan, sans fenetre, et redemarrent seuls en cas de crash.
echo Pour tout arreter : bouton "Arreter" dans l'interface ^(ou stop.bat^).
echo Logs de secours : .run\backend.log et .run\frontend.log ^(sinon onglet Console de l'app^).
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
