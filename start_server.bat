@echo off
chcp 65001 >nul
title MedTriage 多模态智能分诊系统 一键启动
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo   MedTriage - starting server
echo ==========================================
echo.

REM ---- listen port (override with: set MT_PORT=8030) ----
set "PORT=8010"
if not "%MT_PORT%"=="" set "PORT=%MT_PORT%"

REM ---- pick python first: the port probe below needs it ----
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if defined PY goto have_py
if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if defined PY goto have_py
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if defined PY goto have_py
if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if defined PY goto have_py
if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"

:have_py
if not defined PY goto no_python
echo [MedTriage] Python: !PY!
echo.

REM ---- is the port taken, and by whom? ----
REM Old logic treated "something listens on 8000" as "MedTriage already running".
REM That is wrong: any other local service on 8000 made this script open the
REM browser to a foreign app. Now we ASK the listening service whether it is us.
set "PORT_STATE=free"
for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr ":%PORT% " ^| findstr "LISTENING"') do set "PORT_STATE=used"
if "%PORT_STATE%"=="free" goto port_ready

"!PY!" -c "import urllib.request,json,sys;d=json.load(urllib.request.urlopen('http://127.0.0.1:%PORT%/api/health',timeout=2));sys.exit(0 if 'fundus_mode' in d else 1)" >nul 2>nul
if not errorlevel 1 goto already_up

echo [MedTriage] Port %PORT% is taken by another program (health check mismatch).
set "PORT=8020"
echo [MedTriage] Trying port %PORT% instead...
set "PORT_STATE=free"
for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr ":%PORT% " ^| findstr "LISTENING"') do set "PORT_STATE=used"
if "%PORT_STATE%"=="free" goto port_ready
REM 8010 may already be an earlier MedTriage instance: probe before giving up.
"!PY!" -c "import urllib.request,json,sys;d=json.load(urllib.request.urlopen('http://127.0.0.1:%PORT%/api/health',timeout=2));sys.exit(0 if 'fundus_mode' in d else 1)" >nul 2>nul
if not errorlevel 1 goto already_up
echo [ERROR] Ports 8010 and 8020 are both taken.
echo         Close the other program, or start with:  set MT_PORT=8030
pause
exit /b 1

:port_ready
REM ---- load .env if present ----
REM IMPORTANT: only assign when the value is non-empty.
REM A bare "ARK_API_KEY=" in .env would otherwise run "set ARK_API_KEY=",
REM which CLEARS a key already present in the user environment and silently
REM downgrades every LLM feature to demo mode.
if not exist "%~dp0.env" goto after_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do call :setenv "%%A" "%%B"
goto after_env

:setenv
if "%~2"=="" goto :eof
set "%~1=%~2"
goto :eof

:after_env
REM ---- fallback: read ARK_API_KEY from user registry ----
if defined ARK_API_KEY goto after_key
for /f "skip=2 tokens=2,*" %%A in ('reg query "HKCU\Environment" /v ARK_API_KEY 2^>nul') do set "ARK_API_KEY=%%B"

:after_key
if defined ARK_API_KEY goto pick_python_done
echo [WARN] ARK_API_KEY not found, LLM features disabled (demo mode).
echo [WARN] Set it with:  setx ARK_API_KEY "your-key"
echo.

:pick_python_done
REM ---- vue build output check ----
if exist "%~dp0frontend\dist\index.html" goto deps
if not exist "%~dp0frontend\node_modules\vite\bin\vite.js" goto deps
echo [MedTriage] Vue build not found, building frontend first...
cd /d "%~dp0frontend"
node node_modules\vite\bin\vite.js build
cd /d "%~dp0"
echo.

:deps
echo [MedTriage] 检查运行环境，已有依赖不会重复下载。
"!PY!" "%~dp0tools\check_runtime.py"
if errorlevel 1 goto pip_failed
echo [MedTriage] Starting server at http://127.0.0.1:%PORT%
echo [MedTriage] 启动就绪后自动打开浏览器；关闭此窗口可停止服务。
echo.
if not "%MT_NO_BROWSER%"=="1" start "" /b "!PY!" "%~dp0tools\check_runtime.py" --open-browser "http://127.0.0.1:%PORT%/"

:run
cd /d "%~dp0backend"
"!PY!" -m uvicorn main:app --host 127.0.0.1 --port %PORT%
echo.
echo [MedTriage] Server stopped.
pause
exit /b 0

:already_up
echo [MedTriage] MedTriage is already running on port %PORT%.
echo [MedTriage] Opening http://127.0.0.1:%PORT%/
start "" http://127.0.0.1:%PORT%/
timeout /t 3 /nobreak >nul
exit /b 0

:no_python
echo [ERROR] Python not found. Install Python 3.10+ with 'Add to PATH'.
pause
exit /b 1

:pip_failed
echo [ERROR] 运行环境未就绪，请查看上方缺少依赖或加载异常的具体提示。
echo         可双击 04_检查运行环境.bat 仅检查，不会安装任何内容。
pause
exit /b 1
