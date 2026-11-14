@echo off
chcp 65001 >nul
title MedTriage 多模态智能分诊与就医导航系统
cd /d "%~dp0"
call "%~dp0start_server.bat"
