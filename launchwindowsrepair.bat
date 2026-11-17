@echo off
setlocal
title TANNIS - Repair
set "HERE=%~dp0"
cd /d "%HERE%"
echo.
echo  ==================================================
echo   TANNIS REPAIR
echo   Fixes the AI engine and any damaged AI files.
echo   This can take 10 to 30 minutes. Keep the drive
echo   plugged in and stay connected to the internet.
echo  ==================================================
echo.

set OLLAMA_FIX_VER=2
set MODEL_FIX_VER=1
set "TDATA=%LOCALAPPDATA%\TANNIS"
set "OLLAMA_MARKER=%TDATA%\ollama_fix_%OLLAMA_FIX_VER%.txt"
set "MODELS_MARKER=%TDATA%\models_ok_%MODEL_FIX_VER%.txt"
set "SAFE_MARKER=%TDATA%\safe_mode.txt"
set "DRIVEMODELS=%HERE%models"
set "PCMODELS=%USERPROFILE%\.ollama\models"
set "FOUNDBAD="
set "DIDPULL="
set "PULLFAILED="
if not exist "%TDATA%" mkdir "%TDATA%"
if not exist "%PCMODELS%\blobs" mkdir "%PCMODELS%\blobs"
if not exist "%PCMODELS%\manifests" mkdir "%PCMODELS%\manifests"

:: Safe mode question
echo  Were TANNIS replies coming out as @@@@ or random symbols?
echo  Safe mode runs the AI on the processor instead of the graphics card.
echo  It is slower, but it fixes most graphics card problems.
echo.
choice /c YN /n /m "  Turn on SAFE MODE? Press Y for yes or N for no: "
if errorlevel 2 goto safeoff
echo safe> "%SAFE_MARKER%"
echo  Safe mode turned ON.
goto safedone
:safeoff
del "%SAFE_MARKER%" >nul 2>&1
echo  Safe mode turned OFF.
:safedone
echo.

taskkill /F /IM "ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo  Step 1 of 5: Reinstalling the AI engine...
call :doinstall
if not defined OLLAMA_EXE goto installfailed
if defined DOWNLOADED echo done> "%OLLAMA_MARKER%"
if not defined DOWNLOADED echo  Could not download the newest AI engine - keeping the current one.

:ollamaready
echo.
echo  Step 2 of 5: Checking the AI files on the TANNIS drive - this is the slow part...
del "%MODELS_MARKER%" >nul 2>&1
call :verifyall drive

echo.
echo  Step 3 of 5: Copying AI files to this computer...
robocopy "%DRIVEMODELS%\manifests" "%PCMODELS%\manifests" /E /R:2 /W:2 /XF *.tmp *partial* /NP /NFL /NDL /NJH /NJS >nul
robocopy "%DRIVEMODELS%\blobs" "%PCMODELS%\blobs" /E /R:2 /W:2 /XF *.tmp *partial* /NP /NFL /NDL /NJH /NJS >nul

echo.
echo  Step 4 of 5: Checking the AI files on this computer...
call :verifyall pc

echo.
echo  Step 5 of 5: Starting the AI engine and replacing anything damaged...
taskkill /F /IM "ollama app.exe" >nul 2>&1
set "OLLAMA_MODELS="
set "OLLAMA_HOST=127.0.0.1:11434"
if exist "%SAFE_MARKER%" call :safemode
start "" /B "%OLLAMA_EXE%" serve

set TRIES=0
:waitollama
timeout /t 1 /nobreak >nul
set /a TRIES+=1
curl -s -o nul http://127.0.0.1:11434/api/version
if not errorlevel 1 goto ollamaup
if %TRIES% LSS 30 goto waitollama
echo  The AI engine did not start. Restart the computer and run this repair again.
pause
exit /b

:ollamaup
if defined FOUNDBAD call :pullall
call :checkmodel llama3.2:1b
call :checkmodel llama3.2:3b
call :checkmodel qwen2.5-coder:7b
call :checkmodel llama3.1:8b
call :syncall
if not defined PULLFAILED echo done> "%MODELS_MARKER%"
if defined PULLFAILED call :pullwarning
if not defined PULLFAILED echo  Repair complete.

echo  Launching TANNIS...
if not exist "%HERE%app\node_modules_win\electron\dist\electron.exe" goto appmissing
cd /d "%HERE%app"
node_modules_win\electron\dist\electron.exe .
exit