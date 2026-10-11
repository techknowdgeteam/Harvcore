@echo off
tscon %sessionname% /dest:console >nul 2>&1
timeout /t 1 >nul
tscon rdp-tcp#0 /dest:console >nul 2>&1
exit