# verify_desktop.py — 桌面版桥接层(DesktopApi)深度验证
# 用法: .venv\Scripts\python.exe -X utf8 pack\verify_desktop.py
import sys, os, json, time, tempfile, shutil, urllib.parse, collections
sys.path.insert(0, r"G:\chaofen5")
os.environ["VT_VERIFY"] = "1"

from app.api import AppState
from desktop_api import DesktopApi

state = AppState()
api = DesktopApi(state)
results = []

def check(tag, cond, extra=""):
    results.append((tag, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + tag + (" | " + str(extra) if extra else ""))

# ---- 模型库四操作 ----
d = tempfile.mkdtemp(prefix="vt_verify_")
fake_pth = os.path.join(d, "fake_verify_model.pth")
with open(fake_pth, "wb") as f:
    f.write(b"\x80\x03]q\x00." * 1000)
check("model_import", api.invoke("POST", "model/import", {"path": fake_pth})["ok"])
lib = api.invoke("GET", "model_library", {})["data"]["models"]
names = [m["name"] for m in lib]
check("model_lib_contains", "fake_verify_model" in names)
r = api.invoke("POST", "model/rename", {"old": "fake_verify_model", "new": "fake_renamed"})
check("model_rename", r["ok"], r)
r = api.invoke("POST", "model/order", {"order": list(reversed(names))})
check("model_order", r["ok"])
r = api.invoke("POST", "model/delete", {"name": "fake_renamed"})
check("model_delete", r["ok"])

# ---- 队列 + 裁切 copy/replace + 压缩 ----
src = os.path.join(d, "src.png")
try:
    import cv2, numpy as np
    img = np.random.randint(60, 200, (240, 360, 3), dtype=np.uint8)
    cv2.imwrite(src, img)
    have_cv2 = True
except Exception:
    have_cv2 = False
if have_cv2:
    r = api.invoke("POST", "queue", {"paths": [src]})
    check("queue_paths", r["ok"] and r["data"]["added"] == 1)
    fid = r["data"]["files"][0]["id"]
    r = api.invoke("POST", "crop", {"id": fid, "x": 10, "y": 10, "w": 100, "h": 80, "mode": "copy", "save_dir": d})
    check("crop_copy", r["ok"] and r["data"].get("replaced") is False, r["data"])
    crop_token = r["data"].get("id", "")
    crop_path = r["data"].get("path", "")
    r = api.invoke("POST", "crop", {"id": fid, "x": 0, "y": 0, "w": 50, "h": 50, "mode": "replace"})
    check("crop_replace", r["ok"] and r["data"].get("replaced") is True, r["data"])
    r = api.invoke("POST", "compress", {"id": fid})
    check("compress", r["ok"], r["data"])
    r = api.invoke("GET", "file/" + fid, {})
    check("file_data_url", r["ok"] and str(r.get("data_url", "")).startswith("data:image/"))

# ---- 任务控制 + 预览注入 ----
r = api.invoke("POST", "job/control", {"type": "batch", "action": "pause"})
check("job_control_idle_err", not r["ok"])
r = api.invoke("GET", "job/status", {"type": "batch", "since": 0})
check("job_status_idle", r["ok"] and r["data"].get("idle") is True)

# ---- 回归: 前端 api() 把查询串原样带进 route(桌面版进度/预览/删除/预设的关键路径) ----
r = api.invoke("GET", "job/status?type=batch&since=0", {})
check("regress_job_status_query", r["ok"] and r["data"].get("idle") is True)
state.jobs.jobs["batch"] = {
    "job": None, "running": True, "done": False, "error": None, "progress": 33,
    "outputs": [], "logs": collections.deque([(1, "hello")]), "next_seq": 2,
    "preview": None,
}
r = api.invoke("GET", "job/status?type=batch&since=0", {})
check("regress_job_status_query_active", r["ok"] and r["data"].get("idle") is False
      and r["data"].get("progress") == 33 and len(r["data"].get("logs", [])) == 1)
r = api.invoke("GET", "job/status?type=batch&since=999", {})
check("regress_job_status_query_since", r["ok"] and r["data"].get("logs") == [])
del state.jobs.jobs["batch"]
r = api.invoke("DELETE", "queue?id=" + fid, {})
check("regress_queue_delete_query", r["ok"] and all(q["id"] != fid for q in r["data"]["files"]))
r = api.invoke("POST", "queue", {"paths": [src]})
check("queue_readd", r["ok"] and r["data"]["added"] == 1)
fid2 = r["data"]["files"][0]["id"]
r = api.invoke("GET", "inspect?id=" + fid2, {})
check("regress_inspect_query", r["ok"] and r["data"].get("width") == 50, r["data"])

# ---- 目录列表(WebUI 模式目录选择的后端) ----
r = api.invoke("GET", "dir_list", {"path": d})
check("dir_list_ok", r["ok"] and isinstance(r["data"].get("dirs"), list))
r = api.invoke("GET", "dir_list?path=" + urllib.parse.quote(d), {})
check("dir_list_query", r["ok"] and r["data"].get("path") == os.path.abspath(d))
r = api.invoke("GET", "dir_list", {"path": os.path.join(d, "no_such_dir")})
check("dir_list_missing", not r["ok"])

# ---- 输出附带 data_url(工具箱裁切结果展示) ----
r = api.invoke("GET", "output/" + crop_token, {})
check("output_data_url", r["ok"] and str(r["data"].get("data_url", "")).startswith("data:image/")
      and r["data"].get("path"), r["data"])

# ---- 预览注入: 伪造 preview 数据测试缓存路径 ----
if have_cv2:
    fake_out = os.path.join(d, "out.png")
    cv2.imwrite(fake_out, np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8))
    state.file_registry["test_src"] = {"path": src, "name": "src.png", "size": 1, "ext": ".png"}
    token = state.register_output(fake_out)
    state.jobs.jobs["batch"] = {
        "job": None, "running": False, "done": False, "error": None, "progress": 0,
        "outputs": [], "logs": [], "next_seq": 1, "preview": None,
    }
    state.jobs.jobs["batch"]["preview"] = {"src": "/api/file/test_src", "dst": "/api/preview/" + token,
                                            "name": "out.png", "t": time.time()}
    r = api.invoke("GET", "job/status", {"type": "batch", "since": 0})
    pv = r["data"].get("preview") or {}
    check("preview_src_injected", str(pv.get("src", "")).startswith("data:image/"))
    check("preview_dst_injected", str(pv.get("dst", "")).startswith("data:image/"))

# ---- 配置 ----
r = api.invoke("POST", "config", {"webui_theme": "dark"})
check("config_post", r["ok"], r)
r = api.invoke("GET", "config", {})
check("config_get", r["ok"] and r["data"].get("webui_theme") == "dark")

# ---- 清理 ----
try:
    shutil.rmtree(d)
except Exception:
    pass
# 恢复配置
cfg = state.config
cfg["webui_theme"] = cfg.get("webui_theme", "dark")
from core.config_manager import save_config
backup = r"G:\chaofen5\upscale_config.json"
if os.path.exists(backup + ".bak"):
    shutil.copy(backup + ".bak", backup)

fails = [t for t, ok, _ in results if not ok]
print("=" * 40)
print("VERIFY_DESKTOP:", "ALL_PASS" if not fails else "FAILED: " + ",".join(fails))
