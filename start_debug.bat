@echo off
rem Debug launcher: keeps the console so you can see pet.log output.
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" "pet.py"
pause
