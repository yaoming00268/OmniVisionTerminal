# -*- coding: utf-8 -*-
"""E2E v2: PostMessage 模拟点击 WebUI 卡片"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time

user32 = ctypes.windll.user32
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

def find_window(title_part):
    result = []
    def cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if title_part in buf.value and user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0] if result else None

def post_click(hwnd, cx, cy):
    lparam = (cy << 16) | (cx & 0xFFFF)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.15)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)

LAUNCHER = r"G:\chaofen5\pack\dist\App\PhantomLauncher\PhantomLauncher.exe"
LAUNCHER_DIR = r"G:\chaofen5\pack\dist\App\PhantomLauncher"

for proc in ("PhantomCore", "PhantomLauncher"):
    subprocess.run(["taskkill", "/F", "/IM", proc + ".exe"], capture_output=True)
time.sleep(1)

launcher = subprocess.Popen([LAUNCHER], cwd=LAUNCHER_DIR)
hwnd = None
for _ in range(30):
    hwnd = find_window("全能视像解析终端")
    if hwnd:
        break
    time.sleep(0.5)
if not hwnd:
    print("WINDOW_NOT_FOUND")
    raise SystemExit(1)

rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w, h = rect.right - rect.left, rect.bottom - rect.top
print("WIN=(%d,%d) %dx%d" % (rect.left, rect.top, w, h))

# 客户区起点(去掉标题栏, 假设 ~31px)与 WebView2 控件位置
# WebUI 卡片: 中间列, 客户区 y 约 60-480 之间的中段
cx = w // 2
# 尝试多个 y(从上到下), 覆盖卡片区
for cy in (120, 200, 280, 360, 440):
    post_click(hwnd, cx, cy)
    time.sleep(1.0)
    # 每次点击后检查是否已触发(引擎出现即停)
    import psutil
    if any(p.info["name"] == "PhantomCore.exe" for p in psutil.process_iter(['name'])):
        print("ENGINE_UP after click y=%d" % cy)
        break
    if launcher.poll() is not None:
        print("LAUNCHER_EXITED after click y=%d" % cy)
        break

import psutil
engine_up = any(p.info["name"] == "PhantomCore.exe" for p in psutil.process_iter(['name']))
launcher_gone = launcher.poll() is not None
print("ENGINE_UP=%s LAUNCHER_GONE=%s" % (engine_up, launcher_gone))

import socket
sock = socket.socket()
try:
    sock.settimeout(1)
    sock.connect(("127.0.0.1", 7860))
    print("PORT_7860=OPEN")
except Exception:
    print("PORT_7860=CLOSED")
finally:
    sock.close()

subprocess.run(["taskkill", "/F", "/IM", "PhantomCore.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "PhantomLauncher.exe"], capture_output=True)
print("E2E2_END")
