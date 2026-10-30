@echo off
rem AI Studio launcher for Windows: double-click this file.
rem Options are passed through, e.g.  start.bat -Prod   or   start.bat -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
