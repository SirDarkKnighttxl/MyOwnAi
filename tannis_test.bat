@echo off
:: ═══════════════════════════════════════════════════
::   TANNIS DRIVE — PRE-SHIP TEST SCRIPT (WINDOWS)
:: ═══════════════════════════════════════════════════

cd /d "%~dp0"
title TANNIS — Pre-Ship Drive Test

set PASS=0
set FAIL=0
set WARN=0

echo.
echo   T.A.N.N.I.S -- PRE-SHIP DRIVE TEST
echo   Drive path: %~dp0
echo.

:: ── LICENSE ──────────────────────────────────────────
echo -- LICENSE --

if not exist "license.json" (
  echo   [ FAIL ] license.json MISSING
  set /a FAIL+=1
  goto app_files
)
echo   [ PASS ] license.json exists
set /a PASS+=1

powershell -NoProfile -Command "(Get-Content license.json | ConvertFrom-Json).key" > "%TEMP%\tkey.txt" 2>nul
set /p LICENSE_KEY= < "%TEMP%\tkey.txt"
del "%TEMP%\tkey.txt" >nul 2>&1

if "%LICENSE_KEY%"=="" (
  echo   [ FAIL ] license.json has no key field
  set /a FAIL+=1
) else (
  echo   [ PASS ] License key present: %LICENSE_KEY%
  set /a PASS+=1
)

echo.

:: ── APP FILES ─────────────────────────────────────────
:app_files
echo -- APP FILES --

if exist "app\index.html"      ( echo   [ PASS ] app\index.html found      & set /a PASS+=1 ) else ( echo   [ FAIL ] app\index.html MISSING      & set /a FAIL+=1 )
if exist "app\main.js"         ( echo   [ PASS ] app\main.js found         & set /a PASS+=1 ) else ( echo   [ FAIL ] app\main.js MISSING         & set /a FAIL+=1 )
if exist "app\loading.html"    ( echo   [ PASS ] app\loading.html found    & set /a PASS+=1 ) else ( echo   [ FAIL ] app\loading.html MISSING    & set /a FAIL+=1 )
if exist "app\visualizer.html" ( echo   [ PASS ] app\visualizer.html found & set /a PASS+=1 ) else ( echo   [ FAIL ] app\visualizer.html MISSING & set /a FAIL+=1 )
if exist "app\package.json"    ( echo   [ PASS ] app\package.json found    & set /a PASS+=1 ) else ( echo   [ FAIL ] app\package.json MISSING    & set /a FAIL+=1 )
if exist "app\preload.js"      ( echo   [ PASS ] app\preload.js found      & set /a PASS+=1 ) else ( echo   [ WARN ] app\preload.js not found     & set /a WARN+=1 )

if exist "app\package.json" (
  powershell -NoProfile -Command "(Get-Content app\package.json | ConvertFrom-Json).version" > "%TEMP%\tver.txt" 2>nul
  set /p APP_VER= < "%TEMP%\tver.txt"
  del "%TEMP%\tver.txt" >nul 2>&1
  echo   [ PASS ] App version: %APP_VER%
  set /a PASS+=1
)

echo.

:: ── ELECTRON ──────────────────────────────────────────
echo -- ELECTRON (WINDOWS) --

if exist "app\node_modules_win\electron\dist\electron.exe" (
  echo   [ PASS ] Electron Windows binary found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Electron Windows binary MISSING
  set /a FAIL+=1
)

if exist "app\node_modules_mac" (
  echo   [ PASS ] node_modules_mac present
  set /a PASS+=1
) else (
  echo   [ WARN ] node_modules_mac not found — Mac users may need first-time setup
  set /a WARN+=1
)

echo.

:: ── OLLAMA ────────────────────────────────────────────
echo -- OLLAMA --

if exist "ollama\win\ollama.exe" (
  echo   [ PASS ] Ollama Windows binary found
  set /a PASS+=1
) else (
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    echo   [ PASS ] Ollama found in system install
    set /a PASS+=1
  ) else (
    echo   [ WARN ] Ollama not found on drive — OllamaSetup.exe should handle install
    set /a WARN+=1
  )
)

if exist "ollama\win\OllamaSetup.exe" (
  echo   [ PASS ] OllamaSetup.exe installer present
  set /a PASS+=1
) else (
  echo   [ WARN ] OllamaSetup.exe not found
  set /a WARN+=1
)

if exist "ollama\mac\ollama" (
  echo   [ PASS ] Ollama Mac binary found
  set /a PASS+=1
) else (
  echo   [ WARN ] Ollama Mac binary not found
  set /a WARN+=1
)

echo.

:: ── WHISPER ───────────────────────────────────────────
echo -- WHISPER --

if exist "whisper\win\whisper-server.exe" (
  echo   [ PASS ] Whisper Windows binary found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Whisper Windows binary MISSING
  set /a FAIL+=1
)

if exist "whisper\mac\whisper-server" (
  echo   [ PASS ] Whisper Mac binary found
  set /a PASS+=1
) else (
  echo   [ WARN ] Whisper Mac binary not found
  set /a WARN+=1
)

if exist "whisper\mac\models\ggml-base.en.bin" (
  echo   [ PASS ] Whisper model found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Whisper model MISSING
  set /a FAIL+=1
)

echo.

:: ── MODELS ────────────────────────────────────────────
echo -- AI MODELS --

if exist "models\blobs" (
  for /f %%C in ('dir /b "models\blobs\" 2^>nul ^| find /c /v ""') do set BLOB_COUNT=%%C
  if "%BLOB_COUNT%"=="0" (
    echo   [ FAIL ] models\blobs folder is EMPTY
    set /a FAIL+=1
  ) else (
    echo   [ PASS ] Model blobs present — %BLOB_COUNT% files
    set /a PASS+=1
  )
) else (
  echo   [ FAIL ] models\blobs folder MISSING
  set /a FAIL+=1
)

if exist "models\manifests\registry.ollama.ai\library\llama3.2" (
  echo   [ PASS ] Llama 3.2 manifest found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Llama 3.2 manifest MISSING
  set /a FAIL+=1
)

if exist "models\manifests\registry.ollama.ai\library\qwen2.5-coder" (
  echo   [ PASS ] Qwen 2.5 Coder manifest found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Qwen 2.5 Coder manifest MISSING
  set /a FAIL+=1
)

if exist "models\manifests\registry.ollama.ai\library\llama3.1" (
  echo   [ PASS ] Llama 3.1 manifest found
  set /a PASS+=1
) else (
  echo   [ FAIL ] Llama 3.1 manifest MISSING
  set /a FAIL+=1
)

echo.

:: ── CONFIG ────────────────────────────────────────────
echo -- CONFIG --

if exist "config" (
  echo   [ PASS ] config folder exists
  set /a PASS+=1
) else (
  echo   [ WARN ] config folder not found — will be created on first launch
  set /a WARN+=1
)

echo.

:: ── LAUNCH SCRIPTS ────────────────────────────────────
echo -- LAUNCH SCRIPTS --

if exist "launch.bat" (
  echo   [ PASS ] launch.bat found
  set /a PASS+=1
) else (
  echo   [ FAIL ] launch.bat MISSING
  set /a FAIL+=1
)

if exist "launch.sh" (
  echo   [ PASS ] launch.sh found
  set /a PASS+=1
) else (
  echo   [ WARN ] launch.sh not found
  set /a WARN+=1
)

echo.

:: ── LICENSE SERVER PING ───────────────────────────────
echo -- LICENSE SERVER CONNECTIVITY --

powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://tannis-server-production.up.railway.app/health' -TimeoutSec 5 -UseBasicParsing | Out-Null; Write-Host 'REACHABLE' } catch { Write-Host 'UNREACHABLE' }" > "%TEMP%\tping.txt" 2>nul
set /p PING_RESULT= < "%TEMP%\tping.txt"
del "%TEMP%\tping.txt" >nul 2>&1

if "%PING_RESULT%"=="REACHABLE" (
  echo   [ PASS ] Railway license server is reachable
  set /a PASS+=1
) else (
  echo   [ WARN ] Railway license server did not respond
  set /a WARN+=1
)

echo.

:: ── RESULT ────────────────────────────────────────────
echo ===============================================
if %FAIL%==0 (
  echo   ALL CHECKS PASSED -- DRIVE READY TO SHIP
) else (
  echo   CHECK(S) FAILED -- DO NOT SHIP
)
if %WARN% GTR 0 echo   WARNING(S) -- review before shipping
echo   %PASS% passed  %FAIL% failed  %WARN% warnings
echo ===============================================
echo.
pause
exit /b