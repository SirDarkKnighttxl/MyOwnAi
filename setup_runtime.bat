@echo off
rem One-time setup: portable Python 3.12 embeddable runtime in runtime\python.
rem Network is used here only (python.org, bootstrap.pypa.io, PyPI), the same
rem pattern as setup_corpus.py. NOX itself makes no network calls at runtime.
rem Offline alternative: copy a finished runtime\python folder from another
rem NOX machine; every path in it is relative, so it works from any drive.
setlocal EnableExtensions
cd /d "%~dp0"

set "PYVER=3.12.10"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
set "PYSHA256=4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
set "GETPIP=https://bootstrap.pypa.io/get-pip.py"
set "RT=%~dp0runtime"
set "PYDIR=%RT%\python"
set "DL=%RT%\download"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"

if exist "%PYDIR%\python.exe" goto have_python
if not exist "%DL%" mkdir "%DL%"

echo [1/6] Downloading %PYZIP%
%PS% "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%DL%\%PYZIP%'"
if errorlevel 1 goto fail

echo [2/6] Verifying SHA-256
%PS% "if ((Get-FileHash -Algorithm SHA256 -LiteralPath '%DL%\%PYZIP%').Hash -ne '%PYSHA256%') { exit 1 }"
if errorlevel 1 goto badhash

echo [3/6] Unpacking into runtime\python
%PS% "Expand-Archive -Force -LiteralPath '%DL%\%PYZIP%' -DestinationPath '%PYDIR%'"
if errorlevel 1 goto fail

:have_python
echo [4/6] Installing python312._pth (project root on sys.path, site enabled)
copy /Y "%~dp0packaging\python312._pth" "%PYDIR%\python312._pth" >nul
if errorlevel 1 goto fail

"%PYDIR%\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto have_pip
echo [5/6] Bootstrapping pip
if not exist "%DL%" mkdir "%DL%"
%PS% "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%GETPIP%' -OutFile '%DL%\get-pip.py'"
if errorlevel 1 goto fail
"%PYDIR%\python.exe" "%DL%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto fail

:have_pip
echo [6/6] Installing NOX dependencies (requirements.txt)
rem setuptools+wheel first and --no-build-isolation: pip's isolated sdist
rem builds rely on PYTHONPATH, which the ._pth file disables (proxy_tools).
"%PYDIR%\python.exe" -m pip install --no-warn-script-location setuptools wheel
if errorlevel 1 goto fail
"%PYDIR%\python.exe" -m pip install --no-warn-script-location --no-build-isolation -r "%~dp0requirements.txt"
if errorlevel 1 goto fail

"%PYDIR%\python.exe" -c "import fastapi, uvicorn, httpx, webview, sqlite3, noxd.main; print('runtime ok')"
if errorlevel 1 goto fail
if exist "%DL%" rmdir /S /Q "%DL%"
echo Done. run.bat will now use runtime\python\python.exe.
pause
exit /b 0

:badhash
echo SHA-256 mismatch for %PYZIP%; deleting the download. Re-run to retry.
del /Q "%DL%\%PYZIP%" >nul 2>&1
pause
exit /b 1

:fail
echo Setup failed. Fix the error above and re-run setup_runtime.bat (it is safe to re-run).
pause
exit /b 1
