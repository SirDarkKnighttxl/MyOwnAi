@echo off
cd /d C:\Users\DarkK\Projects\NOX
git push
if errorlevel 1 (
  echo.
  echo PUSH FAILED - not mirroring. Fetch and rebase, then re-run.
  pause
  exit /b 1
)
robocopy . E:\NOX /MIR /XD __pycache__ .pytest_cache train\runs /R:3 /W:2 /NFL /NDL
echo.
echo Verifying...
robocopy . E:\NOX /MIR /XD __pycache__ .pytest_cache train\runs /L /NDL /NFL /NJH /NJS /NP > "%TEMP%\noxdiff.txt"
findstr /C:"*" "%TEMP%\noxdiff.txt" >nul 2>&1 && (echo DIFF - see %TEMP%\noxdiff.txt) || (echo MATCH - stick is identical)
pause