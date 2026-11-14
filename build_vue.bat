@echo off
chcp 65001 >nul
title MedTriage Vue Build
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo   MedTriage - build Vue frontend
echo ==========================================
echo.

set "NODE="
if exist "C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe" set "NODE=C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
if defined NODE goto have_node
for /f "delims=" %%P in ('where node 2^>nul') do if not defined NODE set "NODE=%%P"

:have_node
if not defined NODE goto no_node
echo [Build] Node: !NODE!

if not exist "%~dp0frontend\package.json" goto no_app
cd /d "%~dp0frontend"

echo [Build] Type check (vue-tsc)...
"!NODE!" node_modules\vue-tsc\bin\vue-tsc.js --noEmit
if errorlevel 1 goto tsc_failed

echo [Build] Bundling (vite)...
"!NODE!" node_modules\vite\bin\vite.js build
if errorlevel 1 goto vite_failed

echo.
echo [Build] Done. Output: frontend\dist
echo [Build] Now run start_server.bat
echo.
pause
exit /b 0

:no_node
echo [ERROR] node not found. Install Node.js 18+ first.
pause
exit /b 1

:no_app
echo [ERROR] frontend\package.json not found. Are you in the right folder?
pause
exit /b 1

:tsc_failed
echo.
echo [ERROR] Type check failed. Fix the errors above, then run again.
pause
exit /b 1

:vite_failed
echo.
echo [ERROR] Vite build failed. Check the log above.
pause
exit /b 1
