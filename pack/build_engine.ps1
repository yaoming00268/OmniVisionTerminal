$ErrorActionPreference = 'Stop'
$root = 'G:\chaofen5'

Write-Host '[1/5] PyArmor 加密...'
& "$root\.venv\Scripts\pyarmor.exe" gen -O "$root\pack\obf_dist" -r "$root\main.py" "$root\desktop_api.py" "$root\monitor_utils.py" "$root\core" "$root\app"
if ($LASTEXITCODE -ne 0) { Write-Host 'PYARMOR_FAIL'; exit 1 }
Write-Host 'PYARMOR_OK'

Write-Host '[2/5] PyInstaller 封装...'
& "$root\.venv\Scripts\pyinstaller.exe" --noconfirm --onedir --windowed --name "PhantomCore" `
    --specpath "$root\pack" --workpath "$root\pack\build" --distpath "$root\pack\dist" `
    -p "$root\pack\obf_dist" `
    --add-data "$root\web;web" `
    --add-data "$root\pack\obf_dist\core;core" `
    --add-data "$root\pack\obf_dist\app;app" `
    --add-data "$root\pack\obf_dist\desktop_api.py;." `
    --add-data "$root\pack\obf_dist\monitor_utils.py;." `
    --hidden-import pyarmor_runtime_000000 `
    --hidden-import webview `
    --hidden-import desktop_api `
    --hidden-import monitor_utils `
    --hidden-import cv2 `
    --hidden-import torch `
    --hidden-import numpy `
    --hidden-import psutil `
    --hidden-import requests `
    --hidden-import PIL `
    --hidden-import spandrel `
    --hidden-import imageio_ffmpeg `
    --exclude-module tensorrt `
    --exclude-module matplotlib `
    --exclude-module scipy `
    --exclude-module pandas `
    --exclude-module IPython `
    --exclude-module jupyter `
    --exclude-module tkinter `
    --exclude-module PyQt5 `
    --exclude-module PyQt6 `
    --exclude-module gradio `
    --exclude-module moviepy `
    --exclude-module basicsr `
    --exclude-module realesrgan `
    "$root\pack\obf_dist\main.py"
if ($LASTEXITCODE -ne 0) { Write-Host 'PYINSTALLER_FAIL'; exit 1 }
Write-Host 'PYINSTALLER_OK'

Write-Host '[3/5] 拷贝模型库...'
New-Item -ItemType Directory -Force -Path "$root\pack\dist\PhantomCore\models" | Out-Null
Copy-Item "$root\models\*.pth" "$root\pack\dist\PhantomCore\models\" -Force
Copy-Item "$root\models\rife_pytorch_engine" "$root\pack\dist\PhantomCore\models\" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'MODELS_OK'

Write-Host '[4/5] 生成默认配置...'
& "$root\.venv\Scripts\python.exe" -c "import json,sys; sys.path.insert(0,r'G:\chaofen5'); from core.config_manager import DEFAULT_CONFIG; open(r'G:\chaofen5\pack\dist\PhantomCore\upscale_config.json','w',encoding='utf-8').write(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=4))"
Write-Host 'CONFIG_OK'

Write-Host '[5/5] 校验产物...'
$exe = "$root\pack\dist\PhantomCore\PhantomCore.exe"
if (Test-Path $exe) {
    $size = (Get-ChildItem "$root\pack\dist\PhantomCore" -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB
    Write-Host ("ENGINE_OK size={0:N2}GB" -f $size)
} else {
    Write-Host 'ENGINE_MISSING'
    exit 1
}
