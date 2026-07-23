@echo off
REM Arrete l'application Labs autonome (serveur + boucle de supervision).
setlocal

cd /d "%~dp0"
cd ..
set "RUNDIR=%cd%\.run"

echo === Arret d'AI Studio Labs ===
if not exist "%RUNDIR%" mkdir "%RUNDIR%" >nul 2>&1
echo stop > "%RUNDIR%\labs-stop.flag"

REM Demande d'arret propre via l'API (le serveur ecrit aussi le flag)
curl -s -m 3 -X POST http://localhost:8100/api/v1/system/shutdown >nul 2>&1

REM Filet de securite : tuer ce qui ecoute encore sur le port 8100
powershell -NoProfile -Command ^
  "Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

echo Labs arrete.
endlocal
