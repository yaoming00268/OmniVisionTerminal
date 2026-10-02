@echo off
chcp 65001 >nul
title 全能视像解析终端 - Web 版构建脚本
color 0B

echo ===================================================
echo   [全能视像解析终端] Web 版加密与可执行化封装
echo ===================================================
echo.

echo [0/6] 链接虚拟环境...
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo 虚拟环境链接成功！
)

echo.
echo [1/6] 净化历史构建残骸...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist obf_dist rmdir /s /q obf_dist
if exist *.spec del /q *.spec

echo.
echo [2/6] 发动暗影结界 (PyArmor)...
pyarmor gen -O obf_dist -r main.py desktop_api.py monitor_utils.py core app
if %ERRORLEVEL% NEQ 0 (
    echo [致命错误] PyArmor 加密失败。
    pause
    exit /b
)

set FFMPEG_ADD=
if exist "ffmpeg\ffmpeg.exe" set "FFMPEG_ADD=--add-data ffmpeg;ffmpeg"

echo.
echo [3/6] 封装 Web 应用...
pyinstaller --noconfirm --onedir --windowed --name "PhantomCore" ^
    -p obf_dist ^
    --add-data "web;web" ^
    --add-data "models;models" ^
    --add-data "obf_dist\core;core" ^
    --add-data "obf_dist\app;app" ^
    --add-data "obf_dist\desktop_api.py;." ^
    --add-data "obf_dist\monitor_utils.py;." ^
    %FFMPEG_ADD% ^
    --hidden-import pyarmor_runtime_000000 ^
    --hidden-import webview ^
    --hidden-import desktop_api ^
    --hidden-import monitor_utils ^
    --hidden-import cv2 ^
    --hidden-import torch ^
    --hidden-import numpy ^
    --hidden-import psutil ^
    --hidden-import requests ^
    --hidden-import PIL ^
    --hidden-import spandrel ^
    --hidden-import imageio_ffmpeg ^
    --exclude-module tensorrt ^
    --exclude-module matplotlib ^
    --exclude-module scipy ^
    --exclude-module pandas ^
    --exclude-module IPython ^
    --exclude-module jupyter ^
    --exclude-module tkinter ^
    --exclude-module PyQt5 ^
    --exclude-module PyQt6 ^
    --exclude-module gradio ^
    --exclude-module moviepy ^
    --exclude-module basicsr ^
    --exclude-module realesrgan ^
    obf_dist\main.py

if %ERRORLEVEL% NEQ 0 (
    echo [致命错误] PyInstaller 封装失败！
    pause
    exit /b
)

echo.
echo [4/6] 转移模型库 (models)...
mkdir dist\PhantomCore\models 2>nul
xcopy /E /I /Y models dist\PhantomCore\models >nul

echo.
echo [5/6] 抹除锻造痕迹...
rmdir /s /q build
rmdir /s /q obf_dist
del /q PhantomCore.spec 2>nul

echo.
echo ===================================================
echo 封装完成！请前往 dist\PhantomCore 运行主程序，
echo 或直接运行 start_webui.bat 体验 Web 界面。
echo ===================================================
pause
