# -*- coding: utf-8 -*-
"""端到端: 启动打包启动器 -> 模拟点击 WebUI 卡片 -> 验证引擎+浏览器+启动器退出"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time

user32 = ctypes.windll.user32
SW_SHOW = 5
WM_CLOSE = 0x0010

# SendInput 结构
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]

def click(x, y):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    inp.mi.dx, inp.mi.dy = x, y
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    time.sleep(0.1)
    inp.mi.dwFlags = MOUSEEVENTF_LEFTUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

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

LAUNCHER = r"G:\chaofen5\pack\dist\App\PhantomLauncher\PhantomLauncher.exe"
LAUNCHER_DIR = r"G:\chaofen5\pack\dist\App\PhantomLauncher"

# 清理旧引擎
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
    subprocess.run(["taskkill", "/F", "/IM", "PhantomLauncher.exe"], capture_output=True)
    raise SystemExit(1)

rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
print("WIN_RECT=(%d,%d)-(%d,%d)" % (rect.left, rect.top, rect.right, rect.bottom))

# WebUI 卡片: 三卡片中间一张, 卡片区起点约 y=窗口顶+~95, 卡片高约 300
wx = rect.left + (rect.right - rect.left) // 2
wy = rect.top + 240
print("CLICK at (%d, %d)" % (wx, wy))
user32.SetForegroundWindow(hwnd)
time.sleep(0.3)
click(wx, wy)

# 等待: 引擎出现 + 启动器退出 + 端口
engine_up = False
launcher_gone = False
browser_spawned = False
before = set(p.pid for p in __import__("psutil", fromlist=[""]).process_iter(['name'])
             if p.info["name"] and p.info["name"].lower() in ("msedge.exe", "chrome.exe", "firefox.exe"))
for _ in range(40):
    if not launcher_gone and launcher.poll() is not None:
        launcher_gone = True
        print("LAUNCHER_EXITED")
    import psutil
    for p in psutil.process_iter(['name']):
        if p.info["name"] == "PhantomCore.exe":
            engine_up = True
    if engine_up:
        break
    time.sleep(0.5)

print("ENGINE_UP=%s" % engine_up)
import psutil
now = set(p.pid for p in psutil.process_iter(['name'])
          if p.info["name"] and p.info["name"].lower() in ("msedge.exe", "chrome.exe", "firefox.exe"))
new_browsers = now - before
print("NEW_BROWSER_PROC=%s" % (list(new_browsers) or []))
print("LAUNCHER_GONE=%s" % launcher_gone)

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

# 清理
subprocess.run(["taskkill", "/F", "/IM", "PhantomCore.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "PhantomLauncher.exe"], capture_output=True)
for pid in new_browsers:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
print("E2E_END")
