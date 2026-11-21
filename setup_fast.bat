@echo off
if not exist C:\NOX\models mkdir C:\NOX\models
copy /Y "%~dp0models\Qwen3-8B-Q4_K_M.gguf" C:\NOX\models\
echo Installed fast local copy. Delete C:\NOX\models to go portable again.
pause
