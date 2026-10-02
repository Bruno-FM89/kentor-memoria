@echo off
REM Kentor Memoria - clique duas vezes neste arquivo para abrir a interface.
chcp 65001 >nul
cd /d "%~dp0"
title Kentor Memoria

if exist ".venv\instalado.ok" goto preparar

echo.
echo ============================================================
echo  Primeira vez: instalando o Kentor Memoria.
echo  Isso leva alguns minutos. Nao feche esta janela.
echo ============================================================
echo.
python --version >nul 2>&1
if errorlevel 1 goto sem_python
python -m venv .venv
if errorlevel 1 goto erro
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto erro
echo ok> ".venv\instalado.ok"

:preparar
".venv\Scripts\python.exe" scripts\preparar.py
if errorlevel 1 goto erro

echo.
echo ============================================================
echo  Abrindo no navegador: http://localhost:8501
echo  Deixe esta janela aberta enquanto usa.
echo  Para encerrar, feche esta janela.
echo ============================================================
echo.
".venv\Scripts\python.exe" -m kentor_memoria.cli ui
goto fim

:sem_python
echo.
echo Python nao encontrado. Instale em https://www.python.org/downloads/
echo e marque a opcao "Add python.exe to PATH" na primeira tela do instalador.
pause
goto fim

:erro
echo.
echo Algo deu errado. Tire um print desta janela e mande para o Claude.
pause

:fim
