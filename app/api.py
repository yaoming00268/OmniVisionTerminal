import os
import sys
import json
import time
import uuid
import collections
import threading
import subprocess

from core.config_manager import load_config, save_config, DEFAULT_CONFIG
from core.models import get_model_descs
from core.hardware import analyze_hardware, autotune_hardware
from core.compressor import analyze_image_file, crop_image_file, lossless_compress

# 注意: batch_worker / cloud_worker / train_worker / utils 的重型依赖
# (torch / cv2 / numpy / requests) 采用函数内懒加载, 加快服务启动速度。

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "webapp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

OUT_FORMATS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp")
VIDEO_MODES = ("upscale_only", "interp_only", "both")

CONFIG_SCHEMA = {
    "scale": ("float", 1.0, 64.0),
    "block_size": ("int", 256, 4000),
    "keep_slices": ("bool", None, None),
    "slice_dir": ("str", None, None),
    "output_dir": ("str", None, None),
    "output_format": ("str", None, None),
    "use_fast_mode": ("bool", None, None),
    "use_compression": ("bool", None, None),
    "use_cpu": ("bool", None, None),
    "optimize_alpha_channel": ("bool", None, None),
    "model_choice": ("str", None, None),
    "force_custom_res": ("bool", None, None),
    "target_width": ("int", 128, 16384),
    "target_height": ("int", 128, 16384),
    "video_mode": ("str", None, None),
    "interp_ratio": ("int", None, None),
    "bg_image_path": ("str", None, None),
    "train_dataset_dir": ("str", None, None),
    "train_epochs": ("int", 1, 100000),
    "train_batch_size": ("int", 1, 256),
    "train_learning_rate": ("float", 1e-7, 1.0),
    "train_save_freq": ("int", 1, 100000),
    "cloud_api_key": ("str", None, None),
    "cloud_server_url": ("str", None, None),
    "use_cloud_mode": ("bool", None, None),
    "webui_port": ("int", 1, 65535),
    "webui_share": ("bool", None, None),
    "webui_server_name": ("str", None, None),
    "webui_theme": ("str", None, None),
    "silent_mode": ("bool", None, None),
    "default_image_format": ("str", None, None),
    "default_video_format": ("str", None, None),
    "launcher_default_mode": ("str", None, None),
    "show_queue_thumb": ("bool", None, None),
    "show_full_filename": ("bool", None, None),
    "show_result_preview": ("bool", None, None),
    "model_order": ("list", None, None),
}

def _ext(path):
    return os.path.splitext(path)[1].lower()

def _resolve_queue_file(state, file_id):
    with state._lock:
        item = state.file_registry.get(file_id)
        if not item:
            return None
        return item["path"]

class JobManager:
    """任务状态管理: 单活跃任务 + 环形日志缓冲 + 序号增量推送。"""
    MAX_LOGS = 500

    def __init__(self, state):
        self.state = state
        self.jobs = {}
        self._lock = threading.RLock()

    def _log(self, job_type, text):
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None:
                return
            job["logs"].append((job["next_seq"], text))
            job["next_seq"] += 1

    def _progress(self, job_type, pct):
        with self._lock:
            job = self.jobs.get(job_type)
            if job is not None:
                job["progress"] = max(0, min(100, int(pct)))

    def _register_output(self, job_type, path):
        if not path or not os.path.exists(path):
            return
        token = self.state.register_output(path)
        if not token:
            return
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None:
                return
            if token not in [o["id"] for o in job["outputs"]]:
                job["outputs"].append({"id": token, "name": os.path.basename(path),
                                       "size": os.path.getsize(path)})

    def _set_preview(self, job_type, src_path, dst_path):
        """记录最近一张图片的原图/结果预览(供工作台展示, 直到下一张完成)。"""
        if not dst_path or not os.path.exists(dst_path):
            return
        src_id = None
        # 加锁防止多线程并发遍历时 RuntimeError: dictionary changed size during iteration
        with self.state._lock:
            for fid, item in self.state.file_registry.items():
                if item["path"] == src_path:
                    src_id = fid
                    break
        token = self.state.register_output(dst_path)
        if token is None:
            return
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None:
                return
            job["preview"] = {
                "src": f"/api/file/{src_id}" if src_id else None,
                "dst": f"/api/preview/{token}",
                "name": os.path.basename(dst_path),
                "t": time.time(),
            }

    def _done(self, job_type):
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None:
                return
            job["running"] = False
            job["done"] = True
            err = getattr(job["job"], "_error", None)
            if err:
                job["error"] = err
                msg = f"任务失败: {err}"
            else:
                msg = "任务结束。"
            job["logs"].append((job["next_seq"], msg))
            job["next_seq"] += 1
            job["finished_at"] = time.time()

    def start_batch(self, mode):
        from core.batch_worker import BatchUpscaleJob
        with self.state._lock:
            files = [{"id": item["id"], "path": self.state.file_registry[item["id"]]["path"]}
                     for item in self.state.queue if item["id"] in self.state.file_registry]
        if not files:
            raise ValueError("队列为空，请先添加文件。")
        with self._lock:
            if self.jobs.get("batch", {}).get("running") or self.jobs.get("alpha", {}).get("running"):
                raise ValueError("批处理任务正在运行，请等待其完成。")
            config = dict(self.state.config)
            config["optimize_alpha_channel"] = (mode == "alpha")
            job_info = {
                "job": None, "running": True, "done": False, "error": None,
                "progress": 0, "outputs": [], "logs": collections.deque(maxlen=self.MAX_LOGS),
                "next_seq": 1, "mode": mode, "started_at": time.time(), "preview": None,
            }
            self.jobs["batch"] = job_info
            self.jobs["alpha"] = job_info
        job_type = "alpha" if mode == "alpha" else "batch"
        job = BatchUpscaleJob(
            [f["path"] for f in files], config,
            log_callback=lambda m: self._log(job_type, m),
            progress_callback=lambda p: self._progress(job_type, p),
            done_callback=lambda: self._done(job_type),
            result_callback=lambda p: self._register_output(job_type, p),
            image_callback=lambda s, d: self._set_preview(job_type, s, d),
        )
        with self._lock:
            job_info["job"] = job
        job.start()
        self._log(job_type, f"任务已启动 (模式: {mode}, 文件数: {len(files)})")

    def start_cloud(self):
        from core.cloud_worker import CloudJob
        with self.state._lock:
            files = [{"id": item["id"], "path": self.state.file_registry[item["id"]]["path"]}
                     for item in self.state.queue if item["id"] in self.state.file_registry]
        if not files:
            raise ValueError("队列为空，请先添加文件。")
        with self._lock:
            if self.jobs.get("cloud", {}).get("running"):
                raise ValueError("云端任务正在运行，请等待其完成。")
            job_type = "cloud"
            self.jobs[job_type] = {
                "job": None, "running": True, "done": False, "error": None,
                "progress": 0, "outputs": [], "logs": collections.deque(maxlen=self.MAX_LOGS),
                "next_seq": 1, "started_at": time.time(), "preview": None,
            }
        job = CloudJob(
            [f["path"] for f in files], self.state.config,
            log_callback=lambda m: self._log(job_type, m),
            progress_callback=lambda p: self._progress(job_type, p),
            done_callback=lambda: self._done(job_type),
            result_callback=lambda p: self._register_output(job_type, p),
        )
        with self._lock:
            self.jobs[job_type]["job"] = job
        job.start()
        self._log(job_type, f"云端任务已启动 (文件数: {len(files)})")

    def start_train(self):
        from core.train_worker import TrainJob
        with self._lock:
            if self.jobs.get("train", {}).get("running"):
                raise ValueError("训练任务正在运行，请等待其完成。")
        if not self.state.config.get("train_dataset_dir"):
            raise ValueError("请先在设置中填写训练数据集目录。")
        job_type = "train"
        with self._lock:
            self.jobs[job_type] = {
                "job": None, "running": True, "done": False, "error": None,
                "progress": 0, "outputs": [], "logs": collections.deque(maxlen=self.MAX_LOGS),
                "next_seq": 1, "started_at": time.time(), "preview": None,
            }
        job = TrainJob(
            self.state.config,
            log_callback=lambda m: self._log(job_type, m),
            progress_callback=lambda p: self._progress(job_type, p),
            done_callback=lambda: self._done(job_type),
        )
        with self._lock:
            self.jobs[job_type]["job"] = job
        job.start()
        self._log(job_type, "训练任务已启动。")

    def _resolve_job(self, job_type):
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None and job_type in ("batch", "alpha"):
                alt_type = "alpha" if job_type == "batch" else "batch"
                job = self.jobs.get(alt_type)
            return job

    def control(self, job_type, action):
        """任务控制: pause / resume / stop。"""
        job = self._resolve_job(job_type)
        if job is None or not job.get("running"):
            raise ValueError("任务未在运行")
        j = job.get("job")
        if j is None:
            raise ValueError("任务对象不存在")
        if action == "pause":
            if hasattr(j, "pause"):
                j.pause()
                self._log(job_type, "任务已暂停。")
        elif action == "resume":
            if hasattr(j, "resume"):
                j.resume()
                self._log(job_type, "任务已继续。")
        elif action in ("stop", "cancel"):
            if hasattr(j, "stop"):
                j.stop()
                self._log(job_type, "已下达中止指令，正在停止任务...")
            elif hasattr(j, "pause"):
                j.pause()
                self._log(job_type, "任务不支持直接中止，已置为暂停状态。")
        else:
            raise ValueError("未知控制动作")

    def status(self, job_type, since=0):
        with self._lock:
            job = self.jobs.get(job_type)
            if job is None and job_type in ("batch", "alpha"):
                alt_type = "alpha" if job_type == "batch" else "batch"
                job = self.jobs.get(alt_type)
            if job is None:
                return {"idle": True}
            logs = [{"seq": s, "text": t} for s, t in job["logs"] if s > since]
            running = job["running"]
            done = job["done"]
            error = job["error"]
            progress = job["progress"]
            outputs = list(job["outputs"])
            preview = dict(job["preview"]) if isinstance(job.get("preview"), dict) else job.get("preview")
            j = job.get("job")
        paused = False
        stopped = False
        if j is not None and hasattr(j, "is_paused"):
            try:
                paused = j.is_paused()
            except Exception:
                paused = False
        if j is not None and hasattr(j, "is_stopped"):
            try:
                stopped = j.is_stopped()
            except Exception:
                stopped = False
        return {
            "idle": False,
            "running": running,
            "done": done,
            "error": error,
            "progress": progress,
            "outputs": outputs,
            "paused": paused,
            "stopped": stopped,
            "preview": preview,
            "logs": logs,
        }

def threading_lock():
    return threading.RLock()

class AppState:
    def __init__(self):
        self.config = load_config()
        self.queue = []                 # [{id, name, size, ext, is_video, is_image}]
        self.file_registry = {}         # id -> {path, name, size, ext}
        self.output_registry = {}       # id -> {path, name, size}
        self._lock = threading.RLock()
        self.jobs = JobManager(self)

    def register_upload(self, name, data_bytes):
        token = uuid.uuid4().hex
        ext = _ext(name) if name else ""
        save_path = os.path.join(UPLOAD_DIR, f"{token}{ext}")
        with open(save_path, "wb") as f:
            f.write(data_bytes)
        item = {"path": save_path, "name": name or os.path.basename(save_path),
                "size": len(data_bytes), "ext": ext}
        with self._lock:
            self.file_registry[token] = item
        return token

    def register_output(self, path):
        if not path or not os.path.exists(path):
            return None
        token = uuid.uuid4().hex
        # LRU 淘汰: 超过 300 条时移除最旧的 50 条，防止长期运行内存无限增长
        _MAX_OUTPUTS = 300
        _EVICT_COUNT = 50
        with self._lock:
            self.output_registry[token] = {"path": path, "name": os.path.basename(path),
                                           "size": os.path.getsize(path)}
            if len(self.output_registry) > _MAX_OUTPUTS:
                old_keys = list(self.output_registry.keys())[:_EVICT_COUNT]
                for k in old_keys:
                    self.output_registry.pop(k, None)
        return token

    def queue_add(self, token, from_local=False):
        from core.utils import is_video_file, IMAGE_EXTS
        with self._lock:
            item = self.file_registry[token]
            is_vid = is_video_file(item["path"])
            is_img = item["ext"] in IMAGE_EXTS
            w, h = None, None
            if is_img and os.path.isfile(item["path"]):
                try:
                    import cv2
                    import numpy as np
                    temp_img = cv2.imdecode(np.fromfile(item["path"], dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                    if temp_img is not None:
                        h, w = temp_img.shape[:2]
                except Exception:
                    pass
            elif is_vid and os.path.isfile(item["path"]):
                try:
                    import cv2
                    cap = cv2.VideoCapture(item["path"])
                    if cap.isOpened():
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        cap.release()
                except Exception:
                    pass
            item["width"] = w
            item["height"] = h
            entry = {
                "id": token, "name": item["name"], "size": item["size"], "ext": item["ext"],
                "is_video": is_vid, "is_image": is_img, "width": w, "height": h,
            }
            self.queue.append(entry)
        return entry

    def queue_remove(self, file_id=None):
        with self._lock:
            if file_id:
                self.queue = [q for q in self.queue if q["id"] != file_id]
                removed_ids = [file_id]
            else:
                removed_ids = [q["id"] for q in self.queue]
                self.queue = []
            for fid in removed_ids:
                item = self.file_registry.pop(fid, None)
                if item and "path" in item:
                    p = item["path"]
                    try:
                        abs_p = os.path.abspath(p)
                        abs_upload = os.path.abspath(UPLOAD_DIR)
                        if abs_p.startswith(abs_upload) and os.path.isfile(abs_p):
                            os.remove(abs_p)
                    except Exception:
                        pass

def _public_config(config):
    data = dict(config)
    data["cloud_api_key"] = ""
    return data

def _err_json(msg):
    return json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")

# ---------- API 处理函数: 返回 (status, content_type, body_bytes, headers|None) ----------

def api_get_config(state):
    with state._lock:
        cfg = _public_config(state.config)
    return 200, "application/json", json.dumps(cfg, ensure_ascii=False).encode("utf-8"), None

def api_post_config(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, "application/json", _err_json("无效的 JSON"), None
    changed = False
    with state._lock:
        for key, value in data.items():
            if key not in CONFIG_SCHEMA:
                continue
            kind, vmin, vmax = CONFIG_SCHEMA[key]
            try:
                if kind == "bool":
                    value = bool(value)
                elif kind == "int":
                    value = int(value)
                elif kind == "float":
                    value = float(value)
                elif kind == "list":
                    value = value if isinstance(value, list) else []
                else:
                    value = str(value)
            except (TypeError, ValueError):
                continue
            if vmin is not None and value < vmin:
                value = vmin
            if vmax is not None and value > vmax:
                value = vmax
            if key == "output_format":
                value = value if value in OUT_FORMATS else DEFAULT_CONFIG.get("output_format", ".png")
            if key == "video_mode":
                value = value if value in VIDEO_MODES else DEFAULT_CONFIG.get("video_mode", "upscale_only")
            if key == "interp_ratio":
                value = value if value in (2, 4) else DEFAULT_CONFIG.get("interp_ratio", 2)
            state.config[key] = value
            changed = True
        config_snapshot = dict(state.config)
    if changed:
        save_config(config_snapshot)
    return 200, "application/json", json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"), None

def api_get_models(state):
    payload = {"models": get_model_descs(), "model_choice": state.config.get("model_choice", "anime_6B")}
    return 200, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8"), None

# ---------- 模型库管理 ----------

def api_get_model_library(state):
    from core.models import list_model_library
    lib = list_model_library()
    return 200, "application/json", json.dumps({"models": lib}, ensure_ascii=False).encode("utf-8"), None

def api_post_model_rename(state, body):
    from core.models import rename_model
    try:
        data = json.loads(body.decode("utf-8"))
        rename_model(data.get("old", ""), data.get("new", ""))
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_post_model_delete(state, body):
    from core.models import delete_model
    try:
        data = json.loads(body.decode("utf-8"))
        delete_model(data.get("name", ""))
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_post_model_import(state, form):
    from core.models import import_model_file
    for field, filename, data_bytes in form:
        if field == "file" and filename:
            try:
                name = import_model_file(filename, data_bytes)
            except Exception as e:
                return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
            return 200, "application/json", json.dumps({"ok": True, "name": name},
                                                        ensure_ascii=False).encode("utf-8"), None
    return 400, "application/json", _err_json("未收到模型文件"), None

def api_post_model_order(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
        order = data.get("order")
        if not isinstance(order, list):
            raise ValueError("order 必须是数组")
        with state._lock:
            state.config["model_order"] = [str(x) for x in order]
            config_snapshot = dict(state.config)
        save_config(config_snapshot)
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_get_queue(state):
    with state._lock:
        files = list(state.queue)
    return 200, "application/json", json.dumps({"files": files}, ensure_ascii=False).encode("utf-8"), None

def api_post_queue(state, form, body=None):
    added = []
    paths_json = None
    if form is not None:
        for field, filename, data_bytes in form:
            if field == "file" and filename:
                token = state.register_upload(filename, data_bytes)
                added.append(state.queue_add(token))
            elif field == "paths":
                paths_json = data_bytes.decode("utf-8", errors="replace")
    if paths_json is None and body:
        try:
            data = json.loads(body.decode("utf-8"))
            paths = data.get("paths")
            if isinstance(paths, list):
                paths_json = json.dumps(paths)
        except Exception:
            pass
    if paths_json:
        try:
            from core.utils import IMAGE_EXTS, VIDEO_EXTS
            paths = json.loads(paths_json)
            if isinstance(paths, list):
                collected = []
                for p in paths:
                    p = str(p).strip().strip('"')
                    if not p:
                        continue
                    if os.path.isfile(p):
                        collected.append(p)
                    elif os.path.isdir(p):
                        for root, _dirs, names in os.walk(p):
                            for n in sorted(names):
                                if _ext(n) in IMAGE_EXTS or _ext(n) in VIDEO_EXTS:
                                    collected.append(os.path.join(root, n))
                for p in collected:
                    token = uuid.uuid4().hex
                    with state._lock:
                        state.file_registry[token] = {"path": p, "name": os.path.basename(p),
                                                      "size": os.path.getsize(p), "ext": _ext(p)}
                        added.append(state.queue_add(token))
        except Exception:
            pass
    with state._lock:
        files = list(state.queue)
    return 200, "application/json", json.dumps({"files": files, "added": len(added)},
                                                ensure_ascii=False).encode("utf-8"), None

def api_delete_queue(state, query):
    file_id = query.get("id")
    state.queue_remove(file_id)
    with state._lock:
        files = list(state.queue)
    return 200, "application/json", json.dumps({"files": files}, ensure_ascii=False).encode("utf-8"), None

def api_post_job_start(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, "application/json", _err_json("无效的 JSON"), None
    job_type = data.get("type", "batch")
    try:
        if job_type == "batch":
            state.jobs.start_batch("base")
        elif job_type == "alpha":
            state.jobs.start_batch("alpha")
        elif job_type == "cloud":
            state.jobs.start_cloud()
        elif job_type == "train":
            state.jobs.start_train()
        else:
            raise ValueError("未知任务类型")
    except ValueError as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_get_job_status(state, query):
    job_type = query.get("type", "batch")
    try:
        since = int(query.get("since", 0))
    except ValueError:
        since = 0
    payload = state.jobs.status(job_type, since)
    return 200, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8"), None

def api_post_job_control(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, "application/json", _err_json("无效的 JSON"), None
    job_type = data.get("type", "batch")
    action = data.get("action", "")
    try:
        state.jobs.control(job_type, action)
    except ValueError as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_get_file(state, file_id, query=None):
    path = _resolve_queue_file(state, file_id)
    if not path or not os.path.exists(path):
        return 404, "application/json", _err_json("文件不存在"), None
    item = state.file_registry.get(file_id, {})
    is_thumb = False
    if query:
        is_thumb = str(query.get("thumb", "")).strip() in ("1", "true", "yes")
    ctype, body = _serve_image_bytes(path, is_thumb=is_thumb)
    if not body:
        return 404, "application/json", _err_json("图片数据为空"), None
    name = item.get("name", os.path.basename(path))
    headers = {"Content-Disposition": f"inline; filename*=UTF-8''{_quote(name)}"}
    return 200, ctype, body, headers

def api_get_output(state, token):
    item = state.output_registry.get(token)
    if not item or not os.path.exists(item["path"]):
        return 404, "application/json", _err_json("输出不存在"), None
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(item['name'])}"}
    # 返回5元组，由 server 层流式分块发送，避免将整个大文件读入内存
    return 200, "application/octet-stream", None, headers, item["path"]

def _serve_image_bytes(path, max_preview_side=2048, is_thumb=False, max_thumb_side=256):
    """读取图片/视频帧，TIFF 等浏览器不支持的格式转为 JPEG 预览；
    is_thumb=True 时快速缩放到小尺寸（max_thumb_side），用于队列和网格缩略图秒开；
    超过 max_preview_side 的图自动等比缩放，降低预览内存占用。"""
    import cv2
    import numpy as np
    from core.utils import is_video_file
    ext = _ext(path)

    # 1. 视频缩略图提取: 截取第一帧
    if is_video_file(path):
        try:
            cap = cv2.VideoCapture(path)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                max_side = max_thumb_side if is_thumb else max_preview_side
                if max(h, w) > max_side:
                    scale = max_side / max(h, w)
                    frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80 if is_thumb else 90])
                if ok:
                    return "image/jpeg", buf.tobytes()
        except Exception:
            pass
        return "image/jpeg", b""

    # 2. 缩略图模式 (is_thumb): 高性能缩放采样，体积从几十兆降至 ~10KB
    if is_thumb:
        try:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                h, w = img.shape[:2]
                if max(h, w) > max_thumb_side:
                    scale = max_thumb_side / max(h, w)
                    img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok:
                    return "image/jpeg", buf.tobytes()
        except Exception:
            pass

    # 3. 正常图片预览模式
    ctype = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
        ".gif": "image/gif",
    }.get(ext, "image/png")
    body = None
    if ext in (".tif", ".tiff"):
        try:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img is not None:
                h, w = img.shape[:2]
                if max(h, w) > max_preview_side:
                    scale = max_preview_side / max(h, w)
                    img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                if ok:
                    ctype = "image/jpeg"
                    body = buf.tobytes()
                del img
        except Exception:
            body = None
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        # 针对特大图片进行适当缩小预览
        try:
            file_size = os.path.getsize(path)
            if file_size > 4 * 1024 * 1024:
                img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    h, w = img.shape[:2]
                    if max(h, w) > max_preview_side:
                        scale = max_preview_side / max(h, w)
                        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                        if ok:
                            ctype = "image/jpeg"
                            body = buf.tobytes()
                    del img
        except Exception:
            body = None

    if body is None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except Exception:
            body = b""
    return ctype, body

def api_get_preview(state, token):
    item = state.output_registry.get(token)
    if not item or not os.path.exists(item["path"]):
        return 404, "application/json", _err_json("预览不存在"), None
    ctype, body = _serve_image_bytes(item["path"])
    return 200, ctype, body, {"Content-Disposition": "inline"}

def api_post_open_dir(state, body):
    target = None
    try:
        data = json.loads(body.decode("utf-8"))
        target = data.get("path", "")
    except Exception:
        pass
    if not target:
        target = state.config.get("output_dir", "") or PROJECT_ROOT
    if os.path.isfile(target):
        target = os.path.dirname(target)
    if not os.path.isdir(target):
        return 400, "application/json", json.dumps({"error": "目录不存在"}, ensure_ascii=False).encode("utf-8"), None
    try:
        if hasattr(os, "startfile"):
            os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
    except Exception as e:
        return 500, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", b'{"ok":true}', None

def api_get_inspect(state, query):
    file_id = query.get("id", "")
    path = _resolve_queue_file(state, file_id)
    if not path:
        return 404, "application/json", _err_json("文件不存在"), None
    with state._lock:
        item = state.file_registry.get(file_id, {})
        if item.get("width") and item.get("height"):
            return 200, "application/json", json.dumps({"width": item["width"], "height": item["height"], "has_alpha": False}, ensure_ascii=False).encode("utf-8"), None
    try:
        info = analyze_image_file(path)
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", json.dumps(info, ensure_ascii=False).encode("utf-8"), None

def api_get_dir_list(state, query):
    """列出目录下的子目录(WebUI 模式目录选择, 桌面模式走原生对话框)。"""
    path = str(query.get("path") or "").strip()
    if not path:
        path = state.config.get("output_dir", "") or PROJECT_ROOT
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return 404, "application/json", _err_json("目录不存在"), None
    try:
        names = sorted(os.listdir(path))
    except OSError as e:
        return 500, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    parent = os.path.dirname(path)
    dirs = []
    for n in names:
        if n.startswith("."):
            continue
        full = os.path.join(path, n)
        if os.path.isdir(full):
            dirs.append({"name": n, "path": full})
    return 200, "application/json", json.dumps(
        {"path": path, "parent": parent if parent != path else None, "dirs": dirs},
        ensure_ascii=False).encode("utf-8"), None

def api_post_crop(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, "application/json", _err_json("无效的 JSON"), None
    path = _resolve_queue_file(state, data.get("id", ""))
    if not path:
        return 404, "application/json", _err_json("文件不存在"), None
    ext = data.get("ext", ".png")
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    mode = data.get("mode", "copy")
    if mode == "replace":
        # 保存: 直接覆盖原文件
        out_path = path
        replaced = True
    else:
        # 保存为副本: 输出目录或指定目录
        save_dir = data.get("save_dir", "")
        out_dir = save_dir or state.config.get("output_dir", "") or os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(out_dir, f"{base}_crop{ext}")
        replaced = False
    try:
        crop_image_file(path, data.get("x", 0), data.get("y", 0),
                        data.get("w", 100), data.get("h", 100), out_path, ext)
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    token = state.register_output(out_path)
    return 200, "application/json", json.dumps({"id": token, "name": os.path.basename(out_path),
                                                "replaced": replaced},
                                               ensure_ascii=False).encode("utf-8"), None

def api_post_hardware(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
        result = analyze_hardware(int(data["width"]), int(data["height"]), float(data["scale"]))
    except Exception as e:
        return 400, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    return 200, "application/json", json.dumps(result, ensure_ascii=False).encode("utf-8"), None

def api_post_autotune(state):
    result = autotune_hardware()
    if result.get("cuda"):
        state.config["use_cpu"] = False
        state.config["use_fast_mode"] = result["fast"]
        state.config["block_size"] = result["block"]
    else:
        state.config["use_cpu"] = True
        state.config["use_fast_mode"] = False
    save_config(state.config)
    return 200, "application/json", json.dumps(result, ensure_ascii=False).encode("utf-8"), None

def api_post_compress(state, body):
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return 400, "application/json", _err_json("无效的 JSON"), None
    file_id = data.get("id", "")
    path = _resolve_queue_file(state, file_id)
    if not path:
        return 404, "application/json", _err_json("文件不存在"), None
    out_dir = state.config.get("output_dir", "") or os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    comp_path = lossless_compress(path, out_dir, format_choice="webp", quality=90)
    if not comp_path:
        return 500, "application/json", _err_json("压缩失败"), None
    token = state.register_output(comp_path)
    return 200, "application/json", json.dumps({"id": token, "name": os.path.basename(comp_path),
                                                "size": os.path.getsize(comp_path)}, ensure_ascii=False).encode("utf-8"), None

def api_post_package(state):
    from app.package import build_webapp_package
    out_dir = state.config.get("output_dir", "") or PROJECT_ROOT
    try:
        zip_path = build_webapp_package(out_dir)
    except Exception as e:
        return 500, "application/json", json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"), None
    token = state.register_output(zip_path)
    return 200, "application/json", json.dumps({"id": token, "name": os.path.basename(zip_path),
                                                "size": os.path.getsize(zip_path)}, ensure_ascii=False).encode("utf-8"), None

def api_post_bg(state, form):
    for field, filename, data_bytes in form:
        if field == "file" and filename:
            ext = _ext(filename) or ".png"
            save_path = os.path.join(UPLOAD_DIR, f"webapp_bg{ext}")
            with open(save_path, "wb") as f:
                f.write(data_bytes)
            state.config["bg_image_path"] = save_path
            save_config(state.config)
            return 200, "application/json", json.dumps({"ok": True, "path": save_path},
                                                        ensure_ascii=False).encode("utf-8"), None
    return 400, "application/json", _err_json("未收到文件"), None

def api_get_bg(state):
    path = state.config.get("bg_image_path", "")
    if not path or not os.path.exists(path):
        return 404, "application/json", _err_json("未设置背景"), None
    ext = _ext(path)
    ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "image/png")
    with open(path, "rb") as f:
        return 200, ctype, f.read(), None

def _quote(name):
    from urllib.parse import quote
    return quote(name)
