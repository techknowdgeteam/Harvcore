@echo off
title HARVCORE TRADING SUITE - CONTROL CENTER
color 0A

:MENU
cls
echo ============================================================
echo   🎯 HARVCORE TRADING SUITE - CONTROL CENTER
echo ============================================================
echo.
echo   [1] 🚀 Start FAST Window Focus Rotator (5s intervals)
echo   [2] 🛑 Stop All Components
echo   [3] ❌ Exit
echo.
echo ============================================================
echo.

set /p choice="Enter your choice (1-3): "

if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOPALL
if "%choice%"=="3" goto EXIT
goto MENU

:START
cls
echo.
echo ============================================================
echo   STARTING FAST WINDOW FOCUS ROTATOR
echo ============================================================
echo.
echo This will focus AND maximize windows quickly!
echo Switching windows every 5 seconds - NO relaunching!
echo.
echo Make sure all 5 programs are already running in their windows.
echo.
pause
cls
powershell -ExecutionPolicy Bypass -File "%~dp0HARVCORE.ps1"
pause
goto MENU

:STOPALL
cls
echo ============================================================
echo   🛑 STOPPING ALL COMPONENTS
echo ============================================================
echo.

echo [1] Stopping MARKET ANALYSIS...
taskkill /F /FI "WINDOWTITLE eq MARKET ANALYSIS" 2>nul

echo [2] Stopping INVHARV...
taskkill /F /FI "WINDOWTITLE eq INVHARV" 2>nul

echo [3] Stopping SCREEN_AWAKE...
taskkill /F /FI "WINDOWTITLE eq SCREEN_AWAKE" 2>nul

echo [4] Stopping HARVHUB...
taskkill /F /FI "WINDOWTITLE eq HARVHUB" 2>nul

echo [5] Stopping COMMUNICATOR...
taskkill /F /FI "WINDOWTITLE eq COMMUNICATOR" 2>nul

echo.
echo ✅ All trading components stopped successfully!
pause
goto MENU

:EXIT
exit