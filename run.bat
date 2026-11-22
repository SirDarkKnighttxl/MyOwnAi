@echo off
rem Launch NOX. Prefers the portable runtime\python\python.exe (see
rem setup_runtime.bat); falls back to python on PATH.
setlocal EnableExtensions
cd /d "%~dp0"

set "NOX_PY=%~dp0runtime\python\python.exe"
if exist "%NOX_PY%" goto launch

rem Fallback: a real python on PATH. Running it (not just `where`) skips the
rem Microsoft Store alias stub, which exists but cannot run scripts.
set "NOX_PY=python"
python -c "import sys" >nul 2>&1
if errorlevel 1 goto nopython
echo [NOX] runtime\python not found; using python from PATH.

:launch
taskkill /F /IM llama-server.exe >nul 2>&1
"%NOX_PY%" nox.py
if errorlevel 1 pause
exit /b %errorlevel%

:nopython
echo [NOX] No Python found.
echo   Expected the portable runtime at "%~dp0runtime\python\python.exe".
echo   Run setup_runtime.bat once (needs internet), or copy runtime\python from
echo   another NOX machine, or install Python 3.12 and run:
echo   python -m pip install -r requirements.txt
pause
exit /b 1
