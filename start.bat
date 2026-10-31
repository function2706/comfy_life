@echo off
cd /d "%~dp0"
rem exit code 3 = restart requested (in-app update / restart).
rem The loop is one block, parsed once, so updating this file while it runs is safe.
set KURASHI_SUPERVISED=1
for /l %%i in (0,0,1) do (
  python server.py %*
  if not errorlevel 3 (pause
    exit /b)
)
