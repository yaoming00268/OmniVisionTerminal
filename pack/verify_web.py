# verify_web.py — WebUI 模式(HTTP)端到端验证: 目录列表/队列/裁切预览/状态轮询
# 用法: .venv\Scripts\python.exe -X utf8 pack\verify_web.py
import sys, os, json, time, tempfile, shutil, threading, urllib.request, urllib.parse
sys.path.insert(0, r"G:\chaofen5")

from app.server import WebServer

PORT = 17999
BASE = "http://127.0.0.1:%d" % PORT
results = []

def check(tag, cond, extra=""):
    results.append((tag, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + tag + (" | " + str(extra) if extra else ""))

def req(method, path, body=None, ctype="application/json"):
    r = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, data=data, timeout=30) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()

server = WebServer(port=PORT, server_name="127.0.0.1", open_browser=False)
t = threading.Thread(target=server.run, daemon=True)
t.start()
time.sleep(1.5)

# ---- 静态资源: 新 UI 元素与 JS 函数已就位 ----
st, _, html = req("GET", "/index.html")
check("static_index", st == 200)
check("html_has_output_dir_btn", b'id="btnPickOutputDir"' in html)
check("html_has_slice_dir_btn", b'id="btnPickSliceDir"' in html)
check("html_has_crop_save_btn", b'id="btnPickCropSaveDir"' in html)
check("html_has_crop_result", b'id="cropResult"' in html)
check("html_has_dir_modal", b'id="dirBrowserMask"' in html)
st, _, js = req("GET", "/static/js/app.js")
check("static_js", st == 200)
check("js_has_pickDirInto", b"pickDirInto" in js)
check("js_has_showCropResult", b"showCropResult" in js)
check("js_has_fullname_omit", b"if (fullName)" in js)

# ---- 配置 / 状态 ----
st, _, body = req("GET", "/api/config")
cfg = json.loads(body)
check("api_config", st == 200 and "output_dir" in cfg)
st, _, body = req("GET", "/api/job/status?type=batch&since=0")
check("api_job_status_idle", st == 200 and json.loads(body).get("idle") is True)

# ---- 目录列表 ----
st, _, body = req("GET", "/api/dir_list?path=" + urllib.parse.quote(r"G:\chaofen5"))
d = json.loads(body)
check("api_dir_list", st == 200 and isinstance(d.get("dirs"), list)
      and any(x["name"] == "web" for x in d["dirs"]) and d.get("path") == r"G:\chaofen5")
st, _, body = req("GET", "/api/dir_list?path=" + urllib.parse.quote(r"G:\chaofen5\no_such"))
check("api_dir_list_missing", st == 404)

# ---- 队列 + 裁切 + 预览(工具箱裁切结果展示链路) ----
d = tempfile.mkdtemp(prefix="vt_web_")
src = os.path.join(d, "src.png")
import cv2, numpy as np
cv2.imwrite(src, np.random.randint(60, 200, (240, 360, 3), dtype=np.uint8))
st, _, body = req("POST", "/api/queue", {"paths": [src]})
q = json.loads(body)
check("api_queue_paths", st == 200 and q["added"] == 1)
fid = q["files"][0]["id"]
st, _, body = req("GET", "/api/inspect?id=" + fid)
info = json.loads(body)
check("api_inspect", st == 200 and info["width"] == 360 and info["height"] == 240)
st, _, body = req("POST", "/api/crop", {"id": fid, "x": 10, "y": 10, "w": 100, "h": 80,
                                        "mode": "copy", "save_dir": d})
crop = json.loads(body)
check("api_crop", st == 200 and crop.get("id"))
st, ctype, body = req("GET", "/api/preview/" + crop["id"])
check("api_preview_image", st == 200 and ctype.startswith("image/png") and len(body) > 1000)
st, ctype, body = req("GET", "/api/output/" + crop["id"])
check("api_output_bytes", st == 200 and len(body) > 1000)
st, _, body = req("DELETE", "/api/queue?id=" + fid)
q2 = json.loads(body)
check("api_queue_delete_query", st == 200 and all(x["id"] != fid for x in q2["files"]))

# ---- 清理 ----
server.httpd.shutdown()
shutil.rmtree(d)
fails = [t for t, ok, _ in results if not ok]
print("=" * 40)
print("VERIFY_WEB:", "ALL_PASS" if not fails else "FAILED: " + ",".join(fails))
