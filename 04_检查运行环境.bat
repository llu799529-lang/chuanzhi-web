@echo off
chcp 65001 >nul
title MedTriage 运行环境检查 不安装依赖
cd /d "%~dp0"
set "PY=python"
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" tools\check_runtime.py --check-only
echo.
pause
