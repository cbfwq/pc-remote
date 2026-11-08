@echo off
title Stop PC Remote
echo Stopping PC Remote ...
set FOUND=0
for %%P in (8765 8766 8767) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /C:":%%P " ^| findstr /C:"LISTENING"') do (
    echo   port %%P ^-^> PID %%A
    taskkill /PID %%A /F >nul 2>&1
    set FOUND=1
  )
)
if "%FOUND%"=="0" echo   Not running.
echo Done.
ping -n 3 127.0.0.1 >nul
