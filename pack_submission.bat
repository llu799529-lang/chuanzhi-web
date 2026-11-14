@echo off
chcp 65001 >nul
title MedTriage pack submission
cd /d "%~dp0"
REM 生成比赛提交包：构建前端 -> 跑后端测试 -> 干净演示库 -> 密钥扫描 -> zip（默认输出到 D:\MedTriage压缩包）
REM 可选参数：--skip-tests  --no-weights  --include-notes
set "PY=python"
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
"%PY%" tools\pack_submission.py %*
echo.
pause
