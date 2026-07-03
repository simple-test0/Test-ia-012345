@echo off
REM ============================================================
REM  AI Studio - Arret d'urgence
REM
REM  Normalement on arrete l'app avec le bouton "Arreter" de
REM  l'interface. Ce script sert de secours si l'interface est
REM  inaccessible : il pose le stop.flag (les superviseurs
REM  caches s'arretent) puis tue les serveurs sur les ports
REM  8000 (backend) et 5173 (frontend).
REM ============================================================
setlocal

cd /d "%~dp0"
if not exist ".run" mkdir ".run" >nul 2>&1
echo stop > ".run\stop.flag"

echo Arret des serveurs AI Studio...

powershell -NoProfile -Command ^
  "$pids = Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique;" ^
  "foreach ($p in $pids) {" ^
  "  $parent = (Get-CimInstance Win32_Process -Filter \"ProcessId=$p\" -ErrorAction SilentlyContinue).ParentProcessId;" ^
  "  $pp = if ($parent) { Get-Process -Id $parent -ErrorAction SilentlyContinue };" ^
  "  if ($pp -and $pp.ProcessName -match 'python') { taskkill /f /t /pid $parent | Out-Null }" ^
  "  else { taskkill /f /t /pid $p | Out-Null }" ^
  "}"

echo Serveurs arretes.
timeout /t 3 >nul
endlocal
