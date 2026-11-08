@echo off
chcp 65001 >nul
title PC Remote - keep this window open
cd /d "%~dp0"
python remote.py 8765
if errorlevel 1 (
  echo.
  echo Failed to start. Is Python installed and on PATH?
  pause
)
