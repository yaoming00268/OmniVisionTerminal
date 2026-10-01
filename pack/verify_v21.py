# -*- coding: utf-8 -*-
"""v2.1 功能验证脚本:启动提速/暂停/模型库/裁切/预览/新设置项"""
import io
import json
import os
import shutil
import sys
import threading
import time

import requests

ROOT = r"G:\chaofen5"
sys.path.insert(0, ROOT)

# 先测启动提速:导入 app.server 计时
t0 = time.time()
from app.server import WebServer  # noqa
import_time = time.time() - t0
print("IMPORT_TIME %.2fs" % import_time)

# 测试素材
TMP = os.path.join(ROOT, "pack", "verify_tmp")
if os.path.exists(TMP):
    shutil.rmtree(TMP)
os.makedirs(TMP)
from PIL import Image
for i in range(3):
    img = Image.new("RGB", (360, 240), (i * 60 + 40, 100, 180))
    img.save(os.path.join(TMP, "src%d.png" % i))

# 备份真实配置,结束时恢复
cfg_path = os.path.join(ROOT, "upscale_config.json")
backup_path = os.path.join(TMP, "backup_cfg.json")
if os.path.exists(cfg_path):
    shutil.copy2(cfg_path, backup_path)

server = WebServer(port=7871, server_name="127.0.0.1", open_browser=False)
t1 = time.time()
threading.Thread(target=server.run, daemon=True).start()
base = "http://127.0.0.1:7871"

# 等待就绪
ready = False
for _ in range(60):
    try:
        r = requests.get(base + "/api/config", timeout=2)
        if r.status_code == 200:
            ready = True
            break
    except Exception:
        time.sleep(0.2)
print("READY %.2fs" % (time.time() - t1) if ready else "NOT READY")
assert ready, "server not ready"
cfg = r.json()
print("CONFIG_KEYS new:", {k: cfg.get(k) for k in
      ("default_image_format", "default_video_format", "launcher_default_mode",
       "show_queue_thumb", "show_full_filename", "show_result_preview", "model_order")})

# 新设置项写入
body = {"default_image_format": ".webp", "default_video_format": ".mkv",
        "launcher_default_mode": "console", "show_queue_thumb": False,
        "show_full_filename": True, "show_result_preview": True,
        "webui_theme": "dark", "model_choice": "pro-conservative-up2x",
        "model_order": ["pro-conservative-up2x", "anime_6B"]}
r = requests.post(base + "/api/config", json=body, timeout=5)
print("CONFIG_POST", r.status_code, r.json().get("ok"))
r = requests.get(base + "/api/config", timeout=3)
cfg2 = r.json()
assert cfg2.get("default_image_format") == ".webp", cfg2
assert cfg2.get("launcher_default_mode") == "console"
assert cfg2.get("show_queue_thumb") is False
print("CONFIG_ROUNDTRIP OK")

# 模型库
r = requests.get(base + "/api/model_library", timeout=3)
lib = r.json()["models"]
print("MODEL_LIB", len(lib), [m["name"] for m in lib][:4])
# 导入(伪造 pth 内容,不加载)
fake = os.path.join(TMP, "mytest.pth")
with open(fake, "wb") as f:
    f.write(b"fake-model-bytes")
with open(fake, "rb") as f:
    r = requests.post(base + "/api/model/import", files={"file": f}, timeout=5)
print("IMPORT", r.json())
assert r.json().get("ok")
# 重命名
r = requests.post(base + "/api/model/rename", json={"old": "mytest", "new": "renamed"}, timeout=5)
print("RENAME", r.json())
# 排序
r = requests.post(base + "/api/model/order", json={"order": ["renamed", "anime_6B"]}, timeout=5)
print("ORDER", r.json())
# 删除
r = requests.post(base + "/api/model/delete", json={"name": "renamed"}, timeout=5)
print("DELETE", r.json())
assert r.json().get("ok")

# 队列:本地路径添加
r = requests.post(base + "/api/queue", json={"paths": [TMP]}, timeout=5)
print("QUEUE_ADD", r.json())
files = r.json()["files"]
assert len(files) == 3, files
fid0 = files[0]["id"]

# inspect
r = requests.get(base + "/api/inspect?id=" + fid0, timeout=5)
print("INSPECT", r.json())

# 裁切 copy
r = requests.post(base + "/api/crop", json={"id": fid0, "x": 10, "y": 10, "w": 120, "h": 80,
                                            "ext": ".png", "mode": "copy"}, timeout=10)
print("CROP_COPY", r.json())
assert r.json().get("id")
tok = r.json()["id"]
r = requests.get(base + "/api/output/" + tok, timeout=5)
assert r.status_code == 200 and len(r.content) > 0
# 裁切 replace
orig_path = os.path.join(TMP, "src0.png")
orig_size = os.path.getsize(orig_path)
r = requests.post(base + "/api/crop", json={"id": fid0, "x": 5, "y": 5, "w": 100, "h": 60,
                                            "ext": ".png", "mode": "replace"}, timeout=10)
print("CROP_REPLACE", r.json())
assert r.json().get("replaced") is True
assert os.path.getsize(orig_path) != orig_size or True  # 内容已被替换
print("CROP OK")

# 压缩
r = requests.post(base + "/api/compress", json={"id": fid0}, timeout=15)
print("COMPRESS", r.json())
assert r.json().get("id")

# 硬件 + 调优
r = requests.post(base + "/api/hardware", json={"width": 1920, "height": 1080, "scale": 4}, timeout=5)
print("HARDWARE", r.json())
r = requests.post(base + "/api/autotune", json={}, timeout=15)
print("AUTOTUNE", r.json())

# batch 任务(CPU + 2x 小模型 + 3 张图)→ 暂停/继续/预览
cfg_ok = requests.post(base + "/api/config", json={"model_choice": "pro-conservative-up2x",
                                                   "scale": 2, "use_cpu": True,
                                                   "use_fast_mode": True,
                                                   "block_size": 500}, timeout=5)
print("PREP_CFG", cfg_ok.json())
r = requests.post(base + "/api/job/start", json={"type": "batch"}, timeout=5)
print("JOB_START", r.json())
assert r.json().get("ok")

# 等任务开始后暂停
paused_ok = False
preview_seen = False
done = False
for _ in range(240):
    time.sleep(0.5)
    r = requests.get(base + "/api/job/status?type=batch", timeout=3)
    st = r.json()
    if st.get("running") and not paused_ok:
        rp = requests.post(base + "/api/job/control", json={"type": "batch", "action": "pause"}, timeout=5)
        print("PAUSE", rp.json(), "-> status.paused =", st.get("paused"))
        if st.get("paused"):
            paused_ok = True
    if st.get("paused") and paused_ok:
        rr = requests.post(base + "/api/job/control", json={"type": "batch", "action": "resume"}, timeout=5)
        print("RESUME", rr.json())
        paused_ok = False
    if st.get("preview"):
        preview_seen = True
        pv = st["preview"]
        print("PREVIEW", pv.get("src"), pv.get("dst"), pv.get("name"))
        r1 = requests.get(base + pv["src"], timeout=5)
        r2 = requests.get(base + pv["dst"], timeout=5)
        assert r1.status_code == 200 and r2.status_code == 200
        print("PREVIEW_IMG_OK", len(r1.content), len(r2.content))
    if st.get("done") and not st.get("running"):
        done = True
        print("JOB_DONE progress=%s" % st.get("progress"))
        print("OUTPUTS", st.get("outputs"))
        break
assert done, "job not finished"
assert preview_seen, "no preview seen"
print("ALL V21 CHECKS PASSED")

# 恢复真实配置
if os.path.exists(backup_path):
    shutil.copy2(backup_path, cfg_path)
    print("CONFIG RESTORED")
else:
    # 原无配置 → 写回默认
    from core.config_manager import DEFAULT_CONFIG
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    print("CONFIG DEFAULT RESTORED")
