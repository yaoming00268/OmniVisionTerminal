# verify_job_flow.py — 真实任务链路验证: 上传->启动->进度->日志->预览->输出
# 用法: .venv\Scripts\python.exe -X utf8 pack\verify_job_flow.py
import sys, os, json, time, tempfile, shutil, threading, urllib.request
sys.path.insert(0, r"G:\chaofen5")

from app.server import WebServer

PORT = 17997
BASE = "http://127.0.0.1:%d" % PORT

def req(method, path, body=None):
    r = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, data=data, timeout=30) as resp:
        return resp.read()

server = WebServer(port=PORT, server_name="127.0.0.1", open_browser=False)
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1.2)

d = tempfile.mkdtemp(prefix="vt_job_")
try:
    # 用小块测试图 + 保守参数, 保证 CPU 也能快速跑完
    import cv2, numpy as np
    src = os.path.join(d, "src.png")
    cv2.imwrite(src, np.random.randint(60, 200, (64, 64, 3), dtype=np.uint8))
    req("POST", "/api/config", {"scale": 2.0, "block_size": 256, "use_fast_mode": True,
                                "use_cpu": True, "keep_slices": False, "slice_dir": "",
                                "output_dir": d, "output_format": ".png",
                                "show_result_preview": True})
    req("POST", "/api/queue", {"paths": [src]})
    req("POST", "/api/job/start", {"type": "batch"})

    seen_progress, seen_logs, seen_preview, done = False, False, False, False
    deadline = time.time() + 600
    while time.time() < deadline:
        st = json.loads(req("GET", "/api/job/status?type=batch&since=0"))
        if st.get("progress", 0) > 0:
            seen_progress = True
        if st.get("logs"):
            seen_logs = True
        pv = st.get("preview") or {}
        if pv.get("src") and pv.get("dst"):
            seen_preview = True
        if st.get("done") and not st.get("running"):
            done = True
            break
        time.sleep(1.0)

    print("RESULT progress=%s logs=%s preview=%s done=%s error=%s outputs=%d" % (
        seen_progress, seen_logs, seen_preview, done, st.get("error"), len(st.get("outputs") or [])))
    ok = seen_progress and seen_logs and seen_preview and done and not st.get("error")
    # 预览图实际可读
    pv = st.get("preview") or {}
    if ok and pv.get("dst"):
        with urllib.request.urlopen(BASE + pv["dst"], timeout=30) as resp:
            ok = ok and resp.status == 200 and len(resp.read()) > 500
    print("VERIFY_JOB_FLOW:", "ALL_PASS" if ok else "FAILED")
finally:
    server.httpd.shutdown()
    shutil.rmtree(d, ignore_errors=True)
