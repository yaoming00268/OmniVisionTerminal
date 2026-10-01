# pack/gui_check_frozen.py — 启动冻结版 PhantomCore 桌面模式并截图验证
import os
import subprocess
import time

from PIL import ImageGrab

ENGINE = r"G:\chaofen5\pack\dist\PhantomCore\PhantomCore.exe"
SHOT = r"G:\chaofen5\pack\verify_shots\desktop_frozen_v240.png"
TRACE = r"G:\chaofen5\pack\dist\PhantomCore\_internal\desktop_trace.log"

if os.path.exists(TRACE):
    os.remove(TRACE)
proc = subprocess.Popen([ENGINE, "--desktop"], cwd=r"G:\chaofen5\pack\dist\PhantomCore")
try:
    time.sleep(22)
    img = ImageGrab.grab()
    img.save(SHOT)
    print("SHOT_SAVED", SHOT, img.size)
    if os.path.exists(TRACE):
        print("TRACE:")
        print(open(TRACE, encoding="utf-8", errors="replace").read())
    else:
        print("NO_TRACE_LOG")
    print("PROCESS_ALIVE", proc.poll() is None)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    subprocess.run(["taskkill", "/f", "/im", "PhantomCore.exe"], capture_output=True)
print("GUI_CHECK_FROZEN_DONE")
