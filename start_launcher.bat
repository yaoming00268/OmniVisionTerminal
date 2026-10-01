@echo off
chcp 65001 >nul
title 全能视像解析终端 启动器
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" launcher_pwv.py %*
) else if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" launcher_pwv.py %*
) else (
    start "" pythonw launcher_pwv.py %*
)
