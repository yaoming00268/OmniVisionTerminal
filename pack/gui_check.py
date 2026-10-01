# pack/gui_check.py — 启动桌面版(副屏)并截图验证
import os
import subprocess
import sys
import time

import sys
sys.path.insert(0, r"G:\chaofen5")

from PIL import ImageGrab
from monitor_utils import debug_monitor_rect

SHOT_DIR = r"G:\chaofen5\pack\verify_shots"
os.makedirs(SHOT_DIR, exist_ok=True)

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "desktop"
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 16
    name = sys.argv[3] if len(sys.argv) > 3 else "desktop.png"

    if mode == "desktop":
        args = [r"G:\chaofen5\.venv\Scripts\python.exe",
                r"G:\chaofen5\main.py", "--desktop", "--secondary"]
    else:  # launcher
        args = [r"G:\chaofen5\.venv\Scripts\python.exe",
                r"G:\chaofen5\launcher_pwv.py"]
    env = dict(os.environ)
    proc = subprocess.Popen(args, cwd=r"G:\chaofen5", env=env,
                            stdout=open(os.path.join(SHOT_DIR, "gui_out.log"), "w", encoding="utf-8"),
                            stderr=subprocess.STDOUT)
    try:
        time.sleep(wait)
        rect = debug_monitor_rect()
        img = ImageGrab.grab(bbox=(rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]))
        path = os.path.join(SHOT_DIR, name)
        img.save(path)
        print("SHOT_SAVED", path, img.size)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    print("GUI_CHECK_DONE")

if __name__ == "__main__":
    main()
