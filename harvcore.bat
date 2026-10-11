@echo off
title HARVCORE TRADING SUITE - CONTROL CENTER
color 0A

:START
cls
powershell -ExecutionPolicy Bypass -File "%~dp0HARVCORE.ps1"
pause
goto START