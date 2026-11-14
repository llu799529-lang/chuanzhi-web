@echo off
chcp 65001 >nul
title MedTriage live smoke test
cd /d "%~dp0backend"
REM 真实接口冒烟测试：计划 6 次调用，硬上限 8 次；第一个失败即停止。只想省最贵的那次就加 --no-image
set "PY=python"
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
"%PY%" evals\live_smoke.py %*
echo.
pause
