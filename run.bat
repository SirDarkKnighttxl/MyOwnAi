@echo off
cd /d %~dp0
taskkill /F /IM llama-server.exe >nul 2>&1
python nox.py
