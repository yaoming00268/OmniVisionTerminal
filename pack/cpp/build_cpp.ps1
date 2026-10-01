# 全能视像解析终端 — C++ Win32 外壳编译脚本
# 依赖: w64devkit (便携 MinGW, 免安装) 位于本目录 ../toolchain/w64devkit/w64devkit
# 产出: 全能视像解析终端.exe / 全能视像解析终端_WebUI模式.exe
$tool = Join-Path $PSScriptRoot "..\toolchain\w64devkit\w64devkit\bin"
if (-not (Test-Path (Join-Path $tool "g++.exe"))) {
    Write-Host "w64devkit not found at $tool" -ForegroundColor Red
    exit 1
}
$env:Path = "$tool;" + $env:Path
$cpp = $PSScriptRoot

g++ -municode -O2 -mwindows -s -o "$cpp\全能视像解析终端.exe" "$cpp\Launcher.cpp" -lws2_32 -lgdi32 -luser32 -lshell32
if ($LASTEXITCODE -ne 0) { Write-Host "Launcher FAIL" -ForegroundColor Red; exit 1 }
g++ -municode -O2 -mwindows -s -o "$cpp\全能视像解析终端_WebUI模式.exe" "$cpp\WebUiMode.cpp" -lws2_32 -lgdi32 -luser32 -lshell32
if ($LASTEXITCODE -ne 0) { Write-Host "WebUiMode FAIL" -ForegroundColor Red; exit 1 }

Copy-Item "$cpp\全能视像解析终端.exe" "$cpp\..\bin\" -Force
Copy-Item "$cpp\全能视像解析终端_WebUI模式.exe" "$cpp\..\bin\" -Force
Write-Host "CPP BUILD OK" -ForegroundColor Green
