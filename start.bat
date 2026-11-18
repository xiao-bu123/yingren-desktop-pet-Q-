@echo off
rem ==========================================================
rem  Shadow Blade Q - desktop pet launcher
rem  Double-click to run. Prefers .venv, then system pythonw.
rem ==========================================================
setlocal
cd /d "%~dp0"

set "PY=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PY=.venv\Scripts\pythonw.exe"

if exist "%PY%" goto :launch
where pythonw >nul 2>nul
if errorlevel 1 goto :nopython
set "PY=pythonw"

:launch
start "" "%PY%" "pet.py"
exit /b 0

:nopython
echo [ERROR] pythonw not found.
echo         Install Python 3.10+ and run: pip install PySide6
echo.
pause
exit /b 1
