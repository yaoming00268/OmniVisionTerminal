# -*- coding: utf-8 -*-
"""引擎任务卡点定位: 启动打包引擎 -> 上传小图 -> 任务 -> 读 worker_trace.log"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7895"
ENGINE = r"G:\chaofen5\pack\dist\App\PhantomCore\PhantomCore.exe"
ENGINE_DIR = r"G:\chaofen5\pack\dist\App\PhantomCore"
TRACE = os.path.join(ENGINE_DIR, "_internal", "worker_trace.log")

def req(method, path, data=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("HTTP %d BODY=%s" % (e.code, e.read().decode("utf-8", "replace")[:500]))
        raise

def make_png():
    try:
        import cv2
        import numpy as np
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:, :, 2] = 200
        ok, buf = cv2.imencode(".png", img)
        return buf.tobytes()
    except Exception:
        # 纯 PIL 兜底
        from PIL import Image
        im = Image.new("RGB", (64, 64), (200, 30, 30))
        b = io.BytesIO()
        im.save(b, "PNG")
        return b.getvalue()

if os.path.exists(TRACE):
    os.remove(TRACE)

errf = open(os.path.join(ENGINE_DIR, "engine_stderr.log"), "wb")
proc = subprocess.Popen([ENGINE, "--port", "7895", "--no-browser"], cwd=ENGINE_DIR,
                        stderr=errf)
try:
    # 等就绪
    for i in range(60):
        try:
            cfg = req("GET", "/api/config")
            print("READY cfg keys=%d" % len(cfg))
            break
        except Exception:
            time.sleep(0.5)
    else:
        print("ENGINE_NOT_READY")
        sys.exit(1)

    png = make_png()
    in_dir = os.path.join(ENGINE_DIR, "test_in")
    os.makedirs(in_dir, exist_ok=True)
    with open(os.path.join(in_dir, "t1.png"), "wb") as f:
        f.write(png)
    r = req("POST", "/api/queue", {"paths": [os.path.join(in_dir, "t1.png")]})
    print("QUEUE added=%s" % r.get("added"))
    cfg = req("GET", "/api/config")
    cfg["scale"] = 2
    cfg["model_choice"] = "anime_6B"
    cfg["use_cpu"] = True
    cfg["output_dir"] = os.path.join(ENGINE_DIR, "test_out")
    req("POST", "/api/config", cfg)
    r = req("POST", "/api/job/start", {"type": "batch"})
    print("JOB_START", r.get("ok"), r.get("err"))

    last_trace = ""
    for i in range(60):
        time.sleep(2)
        st = req("GET", "/api/job/status?type=batch")
        logs = st.get("logs") or []
        trace_now = ""
        if os.path.exists(TRACE):
            with open(TRACE, encoding="utf-8") as f:
                trace_now = f.read().strip()
        if trace_now != last_trace:
            print("TRACE:\n" + trace_now)
            last_trace = trace_now
        if i % 5 == 0:
            print("POLL %d progress=%s running=%s logs=%d" % (
                i * 2, st.get("progress"), st.get("running"), len(logs)))
        if not st.get("running") and st.get("progress", 0) >= 100:
            print("JOB_DONE")
            break
    else:
        print("JOB_STILL_RUNNING")
        if os.path.exists(TRACE):
            with open(TRACE, encoding="utf-8") as f:
                print("FINAL TRACE:\n" + f.read())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    print("VERIFY_EXIT=0")
