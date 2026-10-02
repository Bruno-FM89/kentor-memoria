@echo off
REM Testa se o computador consegue falar com o OpenRouter (IA).
chcp 65001 >nul
cd /d "%~dp0"
title Testar IA - Kentor Memoria
".venv\Scripts\python.exe" scripts\testar_ia.py
echo.
pause
