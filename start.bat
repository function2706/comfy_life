@echo off
cd /d "%~dp0"
rem exit code 3 = restart requested (in-app update / restart)
set KURASHI_SUPERVISED=1
:run
python server.py %*
if %errorlevel%==3 goto run
pause
