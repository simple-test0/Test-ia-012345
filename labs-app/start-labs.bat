@echo off
REM ============================================================
REM  AI Studio Labs - Application autonome d'entrainement
REM
REM  - Reutilise l'environnement Python du backend (rien a reinstaller)
REM  - Base de donnees dediee (data\db\labs.db), creee automatiquement
REM  - Port 8100, interface servie par le meme serveur (pas de npm)
REM  - Redemarre automatiquement en cas de crash
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "APPDIR=%cd%"
cd ..
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "RUNDIR=%ROOT%\.run"

echo === AI Studio Labs ===
echo.

REM ------------------------------------------------------------
REM  1) L'environnement Python du backend doit exister
REM ------------------------------------------------------------
if not exist "%BACKEND%\.venv\Scripts\python.exe" (
  if exist "%ROOT%\install.bat" (
    echo [setup] Environnement Python manquant : lancement de install.bat...
    set "AI_STUDIO_NOPAUSE=1"
    call "%ROOT%\install.bat"
    if errorlevel 1 (
      echo ERREUR: installation echouee. Consulte install.log puis relance.
      pause
      exit /b 1
    )
    set "AI_STUDIO_NOPAUSE="
  ) else (
    echo ERREUR: %BACKEND%\.venv introuvable. Lance d'abord install.bat a la racine.
    pause
    exit /b 1
  )
)

REM ------------------------------------------------------------
REM  2) Pas de doublon si le serveur tourne deja
REM ------------------------------------------------------------
set "LABS_UP="
curl -s -m 3 -o nul http://localhost:8100/health 2>nul && set "LABS_UP=1"

if not exist "%RUNDIR%" mkdir "%RUNDIR%" >nul 2>&1
if exist "%RUNDIR%\labs-stop.flag" del "%RUNDIR%\labs-stop.flag" >nul 2>&1
if exist "%RUNDIR%\labs.log" del "%RUNDIR%\labs.log" >nul 2>&1

REM ------------------------------------------------------------
REM  3) Boucle de supervision : redemarrage auto apres un crash
REM ------------------------------------------------------------
(
  echo @echo off
  echo title AI Studio - Labs
  echo cd /d "%APPDIR%"
  echo :loop
  echo "%BACKEND%\.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8100 ^>^> "%RUNDIR%\labs.log" 2^>^&1
  echo if exist "%RUNDIR%\labs-stop.flag" exit
  echo echo [%%date%% %%time%%] [labs] serveur arrete, redemarrage dans 3 s ^>^> "%RUNDIR%\labs.log"
  echo timeout /t 3 /nobreak ^>nul
  echo if exist "%RUNDIR%\labs-stop.flag" exit
  echo goto loop
) > "%RUNDIR%\labs_loop.bat"

if defined LABS_UP (
  echo [labs] Deja en cours sur http://localhost:8100
) else (
  echo [labs] Demarrage du serveur sur http://localhost:8100 ^(fenetre cachee^)
  powershell -NoProfile -Command "Start-Process -FilePath '%RUNDIR%\labs_loop.bat' -WindowStyle Hidden"
)
echo.

REM ------------------------------------------------------------
REM  4) Attendre que le serveur reponde, puis ouvrir le navigateur
REM ------------------------------------------------------------
if defined LABS_UP goto :ready
echo [labs] Attente du demarrage...
set /a WAIT=0
:wait_labs
curl -s -m 3 -o nul http://localhost:8100/health 2>nul && goto :ready
set /a WAIT+=1
if %WAIT% geq 60 (
  echo [warn] Le serveur Labs ne repond pas apres 2 minutes.
  echo        Consulte .run\labs.log pour les details.
  goto :ready
)
timeout /t 2 /nobreak >nul
goto :wait_labs
:ready

start "" http://localhost:8100
echo Interface Labs : http://localhost:8100
echo Pour arreter   : bouton "Arreter" dans l'interface ^(ou stop-labs.bat^)
endlocal
