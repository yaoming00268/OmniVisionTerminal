@echo off
chcp 65001 >nul
title 全能视像解析终端 桌面版
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" desktop.py %*
) else if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" desktop.py %*
) else (
    start "" pythonw desktop.py %*
)
