# build_desktop.ps1 — 构建 pywebview 桌面版与启动器 (PyInstaller onedir)
$ErrorActionPreference = 'Stop'
$py  = "G:\chaofen5\.venv\Scripts\python.exe"
$pi  = "G:\chaofen5\.venv\Scripts\pyinstaller.exe"
$root = "G:\chaofen5"
Set-Location $root

$common = @(
  "--noconfirm", "--onedir", "--windowed",
  "--specpath", "pack", "--workpath", "pack\build_desktop", "--distpath", "pack\dist",
  "--collect-all", "webview", "--collect-all", "pythonnet",
  "--exclude-module", "tensorrt", "--exclude-module", "matplotlib",
  "--exclude-module", "scipy", "--exclude-module", "pandas",
  "--exclude-module", "IPython", "--exclude-module", "jupyter",
  "--exclude-module", "tkinter", "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
  "--exclude-module", "gradio", "--exclude-module", "moviepy"
)

Write-Host "=== 1/2 PhantomDesktop ==="
& $pi @common "--name", "PhantomDesktop", "--add-data", "$root\web;web", "--add-data", "$root\models;models", "desktop.py"
if ($LASTEXITCODE -ne 0) { throw "PhantomDesktop build failed" }
# 模型目录放到 exe 同级 (core.models.MODEL_DIR 相对 cwd)
if (Test-Path "pack\dist\PhantomDesktop\models") { Remove-Item "pack\dist\PhantomDesktop\models" -Recurse -Force }
Copy-Item -Recurse "models" "pack\dist\PhantomDesktop\models"
# 首次启动即生成的配置, 预置一份干净的 (避免路径乱码与缺失键)
& $py -c "import sys; sys.path.insert(0, r'$root'); from core.config_manager import DEFAULT_CONFIG; import json; open(r'pack\dist\PhantomDesktop\upscale_config.json','w',encoding='utf-8').write(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))"
if ($LASTEXITCODE -ne 0) { throw "config seed failed" }

Write-Host "=== 2/2 PhantomLauncher ==="
& $pi @common "--name", "PhantomLauncher", "--add-data", "$root\web;web", "launcher_pwv.py"
if ($LASTEXITCODE -ne 0) { throw "PhantomLauncher build failed" }

Write-Host "BUILD_DESKTOP_DONE"
