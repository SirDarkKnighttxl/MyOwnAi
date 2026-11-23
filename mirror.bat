@echo off
cd /d C:\Users\DarkK\Projects\NOX
git push
robocopy . E:\NOX /MIR /XD __pycache__ .pytest_cache /R:3 /W:2 /NFL /NDL
echo.
echo Verifying...
robocopy . E:\NOX /MIR /XD __pycache__ .pytest_cache /L /NDL /NFL /NJH /NJS /NP > "%TEMP%\noxdiff.txt"
for %%A in ("%TEMP%\noxdiff.txt") do if %%~zA==0 (echo MATCH - stick is identical) else (echo DIFF - see %TEMP%\noxdiff.txt)
pause