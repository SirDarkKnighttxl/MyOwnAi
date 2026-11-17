@echo off
setlocal
title TANNIS
set "HERE=%~dp0"
cd /d "%HERE%"
echo.
echo  Initializing TANNIS...
echo.
echo  TIP: Do not click inside this window while TANNIS starts.
echo  If it ever looks frozen, press Enter once.
echo.

:: ================= SETTINGS =================
:: Raise SETUP_VER to make every PC see the first-time question one more time
set SETUP_VER=3
:: ============================================

set "TDATA=%LOCALAPPDATA%\TANNIS"
set "SETUP_MARKER=%TDATA%\setup_done_%SETUP_VER%.txt"
set "SAFE_MARKER=%TDATA%\safe_mode.txt"
set "DRIVEMODELS=%HERE%models"
set "PCMODELS=%USERPROFILE%\.ollama\models"
set "DRIVE_SETUP=%HERE%ollama\win\OllamaSetup.exe"
set "DRIVE_OLLAMA=%HERE%ollama\win\ollama.exe"
set "NEW_SETUP=%TDATA%\OllamaSetup.exe"
set "WHISPER_MODEL=%HERE%whisper\mac\models\ggml-base.en.bin"
set "WHISPER_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
set "MODE=normal"
set "ASKAGAIN="
set "OLLAMA_EXE="
set "NEWENGINE="
set "DLFAILED="
set "FOUNDBAD="
set "DIDPULL="
set "PULLFAILED="
set "ENGINEUP="
if not exist "%TDATA%" mkdir "%TDATA%"
if not exist "%PCMODELS%\blobs" mkdir "%PCMODELS%\blobs"
if not exist "%PCMODELS%\manifests" mkdir "%PCMODELS%\manifests"

:: First time on this computer: ask where to get the AI files from
if not exist "%SETUP_MARKER%" call :askmode

:: Close any running Ollama
taskkill /F /IM "ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: ---------- AI engine ----------
if "%MODE%"=="online" call :engineonline
call :findollama
if not defined OLLAMA_EXE call :enginefromdrive
if not defined OLLAMA_EXE goto noengine

:: ---------- AI models from the drive (first time, when N was picked) ----------
if "%MODE%"=="drive" call :modelsfromdrive

:: ---------- Voice model ----------
call :checkwhisper

:: ---------- Start the AI engine ----------
call :startengine
if not defined ENGINEUP goto enginefailed

:: ---------- Download or repair AI models ----------
set "DOPULL="
if "%MODE%"=="online" set "DOPULL=1"
if defined FOUNDBAD set "DOPULL=1"
if defined DOPULL call :pullall
call :checkmodel llama3.2 1b
call :checkmodel llama3.2 3b
call :checkmodel qwen2.5-coder 7b
call :checkmodel llama3.1 8b

:: ---------- Offer to save new downloads to the drive ----------
set "HAVENEW="
if defined DIDPULL set "HAVENEW=1"
if defined NEWENGINE set "HAVENEW=1"
if defined HAVENEW call :asksave
del /f /q "%NEW_SETUP%" >nul 2>&1
if defined PULLFAILED call :pullwarning

:: ---------- Remember this computer is set up ----------
if "%MODE%"=="normal" goto launchapp
if defined ASKAGAIN goto launchapp
if defined PULLFAILED goto launchapp
if defined DLFAILED goto launchapp
echo done> "%SETUP_MARKER%"

:launchapp
echo.
echo  Launching TANNIS...
if not exist "%HERE%app\node_modules_win\electron\dist\electron.exe" goto appmissing
cd /d "%HERE%app"
node_modules_win\electron\dist\electron.exe .
exit

:: ================= ERROR SCREENS =================

:noengine
echo.
echo  Could not find or install the AI engine.
echo  Connect to the internet and try again, or run launchwindowsrepair.bat
pause
exit /b

:enginefailed
echo.
echo  The AI engine did not start.
echo  Restart the computer and try again.
echo  If this keeps happening, run launchwindowsrepair.bat
echo  Details are saved in: %TDATA%
pause
exit /b

:appmissing
echo.
echo  The TANNIS app files on this drive are missing or damaged.
echo  Please contact Titan Gauntlets support.
pause
exit /b

:: ================= HELPERS =================

:askmode
call :online
echo  ==================================================
echo   FIRST TIME ON THIS COMPUTER
echo.
if defined OFFLINE goto askmodeoffline
echo   You are ONLINE.
goto askmodetext
:askmodeoffline
echo   You are OFFLINE right now.
echo   Downloading needs internet, so for now TANNIS can only
echo   use the AI engine and models already on this drive.
:askmodetext
echo.
echo   Y = Download the newest AI engine and models from the internet.
echo       About 14 GB, can take a while on slow internet.
echo   N = Use the AI engine and models already on this TANNIS drive.
echo  ==================================================
echo.
choice /c YN /n /m "  Download the newest from the internet? Press Y or N: "
if errorlevel 2 goto askmodeno
if defined OFFLINE goto askmodeyesoffline
set "MODE=online"
echo  Got it. TANNIS will download the newest files.
echo.
goto :eof
:askmodeyesoffline
set "MODE=drive"
set "ASKAGAIN=1"
echo.
echo  You are offline, so TANNIS cannot download anything right now.
echo  Using the files on this drive instead. You will be asked again
echo  the next time you start TANNIS on this computer.
echo.
goto :eof
:askmodeno
set "MODE=drive"
echo  OK, using the files on this drive.
echo.
goto :eof

:online
set "OFFLINE="
curl -s -o nul -m 8 https://ollama.com >nul 2>&1
if errorlevel 1 set "OFFLINE=1"
goto :eof

:findollama
set "OLLAMA_EXE="
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "C:\Program Files\Ollama\ollama.exe" set "OLLAMA_EXE=C:\Program Files\Ollama\ollama.exe"
goto :eof

:engineonline
echo  Downloading the newest AI engine from ollama.com...
del /f /q "%NEW_SETUP%" >nul 2>&1
curl -L -f --retry 2 -# -o "%NEW_SETUP%" https://ollama.com/download/OllamaSetup.exe
if errorlevel 1 goto engineonlinefail
echo  Installing the AI engine...
call :runsetup "%NEW_SETUP%"
if not "%SETUPERR%"=="0" goto engineonlinefail
set "NEWENGINE=1"
echo  AI engine updated.
goto :eof
:engineonlinefail
del /f /q "%NEW_SETUP%" >nul 2>&1
set "DLFAILED=1"
echo  Could not download the newest AI engine.
echo  TANNIS will use the one already on this computer or on the drive.
goto :eof

:enginefromdrive
if not exist "%DRIVE_SETUP%" goto enginefromdriveexe
echo  Installing the AI engine from the drive...
call :runsetup "%DRIVE_SETUP%"
call :findollama
if defined OLLAMA_EXE goto :eof
:enginefromdriveexe
if exist "%DRIVE_OLLAMA%" set "OLLAMA_EXE=%DRIVE_OLLAMA%"
if defined OLLAMA_EXE echo  Using the backup AI engine on the drive.
goto :eof

:runsetup
start /wait "" "%~1" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
set "SETUPERR=%errorlevel%"
timeout /t 3 /nobreak >nul
taskkill /F /IM "ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe >nul 2>&1
goto :eof

:safemode
echo  Safe mode is ON - the AI runs on the processor only.
set CUDA_VISIBLE_DEVICES=-1
set HIP_VISIBLE_DEVICES=-1
set ROCR_VISIBLE_DEVICES=-1
set GGML_VK_VISIBLE_DEVICES=-1
set OLLAMA_FLASH_ATTENTION=0
goto :eof

:startengine
set "ENGINEUP="
set "OLLAMA_MODELS="
set "OLLAMA_HOST=127.0.0.1:11434"
if exist "%SAFE_MARKER%" call :safemode
set "ENGINELOG=%TDATA%\ollama.log"
call :launchengine
if defined ENGINEUP goto :eof
if exist "%SAFE_MARKER%" goto :eof
echo  The AI engine is not answering. Trying again in safe mode...
taskkill /F /IM ollama.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo safe> "%SAFE_MARKER%"
call :safemode
set "ENGINELOG=%TDATA%\ollama-safe.log"
call :launchengine
goto :eof

:launchengine
<nul set /p "=  Starting AI engine, this can take up to a minute "
start "" /B cmd /c ""%OLLAMA_EXE%" serve >"%ENGINELOG%" 2>&1"
set TRIES=0
:waitengine
timeout /t 1 /nobreak >nul
<nul set /p "=."
curl -s -f -m 3 -o nul http://127.0.0.1:11434/api/version >nul 2>&1
if not errorlevel 1 goto engineok
set /a TRIES+=1
if %TRIES% LSS 45 goto waitengine
echo.
goto :eof
:engineok
echo.
echo  AI engine is running.
set "ENGINEUP=1"
goto :eof

:checkwhisper
set "WSIZE=0"
if exist "%WHISPER_MODEL%" for %%A in ("%WHISPER_MODEL%") do set "WSIZE=%%~zA"
if %WSIZE% GEQ 140000000 goto :eof
echo  The voice model on the drive is missing or damaged.
call :online
if defined OFFLINE goto whisperoffline
echo  Downloading a fresh voice model, about 150 MB...
if not exist "%HERE%whisper\mac\models" mkdir "%HERE%whisper\mac\models"
del /f /q "%WHISPER_MODEL%.tmp" >nul 2>&1
curl -L -f --retry 2 -# -o "%WHISPER_MODEL%.tmp" "%WHISPER_URL%"
if errorlevel 1 goto whisperfail
move /Y "%WHISPER_MODEL%.tmp" "%WHISPER_MODEL%" >nul
if errorlevel 1 goto whisperfail
echo  Voice model fixed.
goto :eof
:whisperfail
del /f /q "%WHISPER_MODEL%.tmp" >nul 2>&1
echo  Could not download the voice model. Voice may not work this time.
goto :eof
:whisperoffline
echo  You are offline, so voice may not work until you start TANNIS online.
goto :eof

:modelsfromdrive
echo  Copying the AI models from the drive to this computer.
echo  This can take a few minutes. Please do not unplug the drive.
robocopy "%DRIVEMODELS%\manifests" "%PCMODELS%\manifests" /E /XO /R:2 /W:2 /XF *.tmp *partial* /NP /NFL /NDL /NJH /NJS >nul
robocopy "%DRIVEMODELS%\blobs" "%PCMODELS%\blobs" /E /XO /R:2 /W:2 /XF *.tmp *partial* /NP /NFL /NDL /NJH /NJS >nul
echo  Checking the AI files for damage. This can take a few minutes...
call :verifymodel llama3.2 1b
call :verifymodel llama3.2 3b
call :verifymodel qwen2.5-coder 7b
call :verifymodel llama3.1 8b
if defined FOUNDBAD echo  Some files could not be fixed from the drive. They will be downloaded.
if not defined FOUNDBAD echo  AI files look good.
goto :eof

:verifymodel
set "VMAN=%PCMODELS%\manifests\registry.ollama.ai\library\%~1\%~2"
if not exist "%VMAN%" set "VMAN=%DRIVEMODELS%\manifests\registry.ollama.ai\library\%~1\%~2"
if not exist "%VMAN%" goto :eof
echo    Checking %~1 %~2...
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$m = ConvertFrom-Json -InputObject (Get-Content -Raw -LiteralPath $env:VMAN); (@($m.config.digest) + @($m.layers.digest)) -replace ':','-'"`) do call :checkblob "%PCMODELS%\blobs\%%D" "%%D" "%DRIVEMODELS%\blobs\%%D"
goto :eof

:checkblob
:: %1 = file to check   %2 = its name   %3 = backup copy to fix it from (optional)
if not exist "%~1" goto tryother
set "WANT=%~2"
set "WANT=%WANT:sha256-=%"
set "GOT="
for /f "delims=" %%H in ('certutil -hashfile "%~1" SHA256 ^| findstr /v /c:":"') do if not defined GOT set "GOT=%%H"
if not defined GOT goto badblob
set "GOT=%GOT: =%"
if /i "%GOT%"=="%WANT%" goto :eof
:badblob
echo    Found a damaged file - fixing it...
del /f /q "%~1" >nul 2>&1
:tryother
if "%~3"=="" goto cantfix
if not exist "%~3" goto cantfix
call :checkblob "%~3" "%~2"
if not exist "%~3" goto cantfix
copy /Y "%~3" "%~1.tmp" >nul
if errorlevel 1 goto cantfix
move /Y "%~1.tmp" "%~1" >nul
echo    Fixed using the good copy.
goto :eof
:cantfix
del /f /q "%~1.tmp" >nul 2>&1
set "FOUNDBAD=1"
goto :eof

:pullall
call :online
if defined OFFLINE set "PULLFAILED=1"
if defined OFFLINE goto :eof
echo.
echo  Downloading the AI models. Please do not unplug the drive.
call :pullone llama3.2:1b
call :pullone llama3.2:3b
call :pullone qwen2.5-coder:7b
call :pullone llama3.1:8b
goto :eof

:pullone
echo    Downloading %~1...
"%OLLAMA_EXE%" pull %~1
if errorlevel 1 set "PULLFAILED=1"
if not errorlevel 1 set "DIDPULL=1"
goto :eof

:checkmodel
:: %1 = model name   %2 = size tag
"%OLLAMA_EXE%" show %~1:%~2 >nul 2>&1
if not errorlevel 1 goto :eof
echo  %~1 %~2 is missing on this computer - fixing it...
call :copymodel "%DRIVEMODELS%" "%PCMODELS%" %~1 %~2
"%OLLAMA_EXE%" show %~1:%~2 >nul 2>&1
if not errorlevel 1 goto :eof
call :online
if defined OFFLINE set "PULLFAILED=1"
if defined OFFLINE goto :eof
call :pullone %~1:%~2
goto :eof

:copymodel
:: %1 = from models folder   %2 = to models folder   %3 = model name   %4 = size tag
set "CM_FROM=%~1"
set "CM_TO=%~2"
set "CM_MAN=%~1\manifests\registry.ollama.ai\library\%~3\%~4"
set "CM_MANDIR=%~2\manifests\registry.ollama.ai\library\%~3"
set "CM_FAIL="
if not exist "%CM_MAN%" set "CM_FAIL=1"
if not exist "%CM_MAN%" goto :eof
echo    Copying %~3 %~4, please wait...
if not exist "%CM_TO%\blobs" mkdir "%CM_TO%\blobs"
if not exist "%CM_MANDIR%" mkdir "%CM_MANDIR%"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$m = ConvertFrom-Json -InputObject (Get-Content -Raw -LiteralPath $env:CM_MAN); (@($m.config.digest) + @($m.layers.digest)) -replace ':','-'"`) do call :copyblob "%%D"
if defined CM_FAIL goto :eof
copy /Y "%CM_MAN%" "%CM_MANDIR%\%~4" >nul
if errorlevel 1 set "CM_FAIL=1"
goto :eof

:copyblob
set "CB_SRC=%CM_FROM%\blobs\%~1"
set "CB_DST=%CM_TO%\blobs\%~1"
if not exist "%CB_SRC%" set "CM_FAIL=1"
if not exist "%CB_SRC%" goto :eof
call :samesize "%CB_SRC%" "%CB_DST%"
if defined SAME goto :eof
copy /Y "%CB_SRC%" "%CB_DST%.tmp" >nul
if errorlevel 1 goto copyblobfail
move /Y "%CB_DST%.tmp" "%CB_DST%" >nul
if errorlevel 1 goto copyblobfail
goto :eof
:copyblobfail
del /f /q "%CB_DST%.tmp" >nul 2>&1
set "CM_FAIL=1"
goto :eof

:samesize
set "SAME="
if not exist "%~2" goto :eof
if "%~z1"=="%~z2" set "SAME=1"
goto :eof

:asksave
echo.
echo  ==================================================
echo   TANNIS downloaded new AI files to this computer.
echo   Save them to your TANNIS drive too? Then the drive is
echo   up to date for the next computer. This can take a while.
echo  ==================================================
echo.
choice /c YN /n /m "  Save the new files to the drive? Press Y or N: "
if errorlevel 2 goto asksaveno
if defined DIDPULL call :syncall
if defined NEWENGINE call :saveengine
echo  Done saving to the drive.
echo.
goto :eof
:asksaveno
echo  OK, the drive was not changed.
echo.
goto :eof

:syncall
echo  Saving the AI models to the TANNIS drive...
set "SYNCBAD="
call :syncone llama3.2 1b
call :syncone llama3.2 3b
call :syncone qwen2.5-coder 7b
call :syncone llama3.1 8b
if defined SYNCBAD echo    Some models could not be saved. The drive may be full.
if not defined SYNCBAD call :cleandrive
goto :eof

:syncone
call :copymodel "%PCMODELS%" "%DRIVEMODELS%" %1 %2
if defined CM_FAIL set "SYNCBAD=1"
goto :eof

:saveengine
if not exist "%NEW_SETUP%" goto :eof
echo  Saving the new AI engine installer to the drive...
if not exist "%HERE%ollama\win" mkdir "%HERE%ollama\win"
copy /Y "%NEW_SETUP%" "%DRIVE_SETUP%.tmp" >nul
if errorlevel 1 goto saveenginefail
move /Y "%DRIVE_SETUP%.tmp" "%DRIVE_SETUP%" >nul
if errorlevel 1 goto saveenginefail
goto :eof
:saveenginefail
del /f /q "%DRIVE_SETUP%.tmp" >nul 2>&1
echo    Could not save the AI engine to the drive. It may be full.
goto :eof

:cleandrive
echo  Cleaning up old AI files on the TANNIS drive...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = $env:DRIVEMODELS; $keep = @{}; $bad = $false; if (-not (Test-Path -LiteralPath (Join-Path $d 'manifests'))) { exit }; foreach ($f in Get-ChildItem -LiteralPath (Join-Path $d 'manifests') -Recurse -File) { try { $j = ConvertFrom-Json -InputObject (Get-Content -Raw -LiteralPath $f.FullName); foreach ($g in (@($j.config.digest) + @($j.layers.digest))) { if ($g) { $keep[($g -replace ':','-')] = 1 } } } catch { $bad = $true } }; if ($bad -or $keep.Count -eq 0) { Write-Output '    Skipped cleanup to keep your files safe.'; exit }; $freed = 0; foreach ($b in Get-ChildItem -LiteralPath (Join-Path $d 'blobs') -File) { if ($b.Name -like 'sha256-*' -and -not $keep.ContainsKey($b.Name)) { $freed += $b.Length; Remove-Item -LiteralPath $b.FullName -Force -ErrorAction SilentlyContinue } }; Write-Output ('    Freed ' + [math]::Round($freed / 1GB, 1) + ' GB on the TANNIS drive.')"
goto :eof

:pullwarning
echo.
echo  WARNING: Some AI files could not be downloaded because this computer
echo  is offline or the download failed. TANNIS will use the copies on the
echo  drive where it can. Connect to the internet and start TANNIS again
echo  to finish setting up.
echo.
pause
goto :eof
