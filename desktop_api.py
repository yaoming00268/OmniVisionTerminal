# desktop_api.py — 桌面版(pywebview)桥接层
# 直接复用 app/api.py 的 API 函数(返回 (status, ctype, body, headers) 元组),
# 在本地把 HTTP 语义转换为 JS 可用的 JSON, 不启动任何 HTTP 服务。
# 前端在 pywebview 环境下调用 window.pywebview.api.invoke(method, route, payload)。
import os
import json
import base64
import time

MEDIA_FILTER = (
    "图片/视频文件 (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;*.gif;"
    "*.mp4;*.avi;*.mkv;*.mov;*.flv;*.wmv;*.webm;*.mpg;*.mpeg;*.m4v;*.ts;*.vob;*.3gp)",
    "所有文件 (*.*)",
)


class DesktopApi:
    """pywebview js_api: 所有方法返回 JSON 可序列化 dict。"""

    def __init__(self, state):
        self.state = state
        self._img_cache = {}   # url -> (mtime, data_url)
        self._win = None

    def set_window(self, win):
        self._win = win

    def _get_window(self):
        if self._win is not None:
            return self._win
        try:
            import webview
            if getattr(webview, "windows", None):
                return webview.windows[0]
        except Exception:
            pass
        return None

    # ---------------- pywebview 入口 ----------------

    def invoke(self, method, route, payload=None):
        try:
            return self._dispatch(str(method or "GET"), str(route or ""),
                                  payload if isinstance(payload, dict) else {})
        except Exception as e:
            return {"ok": False, "status": 500, "error": str(e)}

    def _dispatch(self, method, route, payload):
        from app import api as A
        from urllib.parse import parse_qs
        state = self.state
        # 前端 api() 会把查询串原样带进 route (如 "job/status?type=batch&since=0"),
        # 与 WebServer 的 query 解析保持一致: 拆分查询串并合并进 payload。
        route, _, query = str(route).partition("?")
        if query:
            merged = {k: v[0] for k, v in parse_qs(query).items()}
            if isinstance(payload, dict):
                merged.update(payload)
            payload = merged
        if route == "config":
            if method == "GET":
                return self._json(A.api_get_config(state))
            return self._json(A.api_post_config(state, self._body(payload)))
        if route == "models":
            return self._json(A.api_get_models(state))
        if route == "model_library":
            return self._json(A.api_get_model_library(state))
        if route == "model/rename":
            return self._json(A.api_post_model_rename(state, self._body(payload)))
        if route == "model/delete":
            return self._json(A.api_post_model_delete(state, self._body(payload)))
        if route == "model/import":
            return self._json(A.api_post_model_import(state, self._form_from_payload(payload)))
        if route == "model/order":
            return self._json(A.api_post_model_order(state, self._body(payload)))
        if route == "queue":
            if method == "GET":
                return self._json(A.api_get_queue(state))
            if method == "DELETE":
                return self._json(A.api_delete_queue(state, {"id": payload.get("id")}))
            return self._json(self._queue_add(payload))
        if route == "job/start":
            return self._json(A.api_post_job_start(state, self._body(payload)))
        if route == "job/status":
            result = self._json(A.api_get_job_status(state, payload))
            data = result.get("data")
            if result.get("ok") and isinstance(data, dict):
                self._inject_preview(data)
            return result
        if route == "job/control":
            return self._json(A.api_post_job_control(state, self._body(payload)))
        if route.startswith("file/"):
            return self._image(A.api_get_file(state, route[len("file/"):], query=payload if isinstance(payload, dict) else None))
        if route.startswith("preview/"):
            return self._image(A.api_get_preview(state, route[len("preview/"):]))
        if route.startswith("output/"):
            return self._output(state, A.api_get_output(state, route[len("output/"):]), route[len("output/"):])
        if route == "open_dir":
            return self._json(A.api_post_open_dir(state, self._body(payload)))
        if route == "inspect":
            return self._json(A.api_get_inspect(state, payload))
        if route == "dir_list":
            return self._json(A.api_get_dir_list(state, payload))
        if route == "crop":
            return self._json(A.api_post_crop(state, self._body(payload)))
        if route == "hardware":
            return self._json(A.api_post_hardware(state, self._body(payload)))
        if route == "autotune":
            return self._json(A.api_post_autotune(state))
        if route == "compress":
            return self._json(A.api_post_compress(state, self._body(payload)))
        if route == "package":
            return self._json(A.api_post_package(state))
        if route == "bg":
            if method == "GET":
                return self._image(A.api_get_bg(state))
            return self._json(A.api_post_bg(state, self._form_from_payload(payload)))
        # ------- 桌面扩展 -------
        if route == "pick_files":
            return self._pick_files()
        if route == "pick_dir":
            return self._pick_dir()
        if route == "reveal":
            return self._reveal(payload)
        if route == "open_folder":
            return self._open_folder(payload)
        return {"ok": False, "status": 404, "error": "未知接口"}

    # ---------------- 队列(本地路径直注册, 不复制文件) ----------------

    def _queue_add(self, payload):
        from app import api as A
        paths = payload.get("paths")
        if isinstance(paths, list) and paths:
            return A.api_post_queue(self.state, None,
                                    json.dumps({"paths": paths}).encode("utf-8"))
        uploads = payload.get("uploads")
        if isinstance(uploads, list) and uploads:
            form = []
            for u in uploads:
                if not isinstance(u, dict) or not u.get("name") or not u.get("b64"):
                    continue
                try:
                    data = base64.b64decode(u["b64"])
                except Exception:
                    continue
                form.append(("file", u["name"], data))
            return A.api_post_queue(self.state, form)
        return A.api_post_queue(self.state, None, b'{"paths": []}')

    # ---------------- 响应转换 ----------------

    def _body(self, payload):
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _form_from_payload(self, payload):
        if not isinstance(payload, dict):
            return []
        path = payload.get("path")
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return [("file", os.path.basename(path), f.read())]
        b64 = payload.get("b64")
        if b64:
            name = payload.get("name") or "upload.pth"
            try:
                return [("file", name, base64.b64decode(b64))]
            except Exception:
                return []
        return []

    def _json(self, result):
        status, _ctype, body, _headers = result
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}
        if 200 <= status < 300:
            return {"ok": True, "status": status, "data": data}
        return {"ok": False, "status": status,
                "error": data.get("error") if isinstance(data, dict) else "请求失败"}

    def _image(self, result):
        status, ctype, body, _headers = result
        if status != 200 or not body:
            return {"ok": False, "status": status, "error": "图片不存在"}
        return {"ok": True, "status": 200, "data_url": "data:%s;base64,%s"
                % (ctype, base64.b64encode(body).decode("ascii"))}

    def _output(self, state, result, token):
        status, _ctype, _body, _headers = result
        if status != 200:
            return {"ok": False, "status": status, "error": "输出不存在"}
        item = state.output_registry.get(token) or {}
        data = {"name": item.get("name", "output"), "path": item.get("path", ""),
                "size": item.get("size", 0)}
        # 附带 data_url, 供工具箱裁切结果等场景直接在界面展示图片
        data_url = self._cached_img("/api/preview/" + token)
        if data_url.startswith("data:"):
            data["data_url"] = data_url
        return {"ok": True, "status": 200, "data": data}

    # ---------------- 预览图缓存(轮询无开销) ----------------

    def _inject_preview(self, data):
        pv = data.get("preview")
        if not isinstance(pv, dict):
            return
        for key in ("src", "dst"):
            url = pv.get(key)
            if url:
                pv[key] = self._cached_img(url)

    def _url_to_path(self, url):
        route = url[len("/api/"):] if url.startswith("/api/") else url
        if route.startswith("file/"):
            item = self.state.file_registry.get(route[len("file/"):])
            return item["path"] if item else None
        if route.startswith("preview/"):
            item = self.state.output_registry.get(route[len("preview/"):])
            return item["path"] if item else None
        return None

    def _cached_img(self, url):
        path = self._url_to_path(url)
        if not path or not os.path.isfile(path):
            return url
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return url
        hit = self._img_cache.get(url)
        if hit and hit[0] == mtime:
            return hit[1]
        from app import api as A
        ctype, body = A._serve_image_bytes(path)
        if not body:
            return url
        data_url = "data:%s;base64,%s" % (ctype, base64.b64encode(body).decode("ascii"))
        self._img_cache[url] = (mtime, data_url)
        return data_url

    # ---------------- 系统对话框 / 资源管理器 ----------------

    def _pick_files(self):
        import webview
        win = self._get_window()
        if win is None:
            return {"ok": False, "error": "窗口不可用"}
        try:
            res = win.create_file_dialog(webview.OPEN_DIALOG,
                                         allow_multiple=True, file_filter=MEDIA_FILTER)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not res:
            return {"ok": True, "paths": []}
        if isinstance(res, str):
            res = [res]
        return {"ok": True, "paths": [os.path.abspath(p) for p in res if p]}

    def _pick_dir(self):
        import webview
        win = self._get_window()
        if win is None:
            return {"ok": False, "error": "窗口不可用"}
        try:
            res = win.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not res:
            return {"ok": True, "path": ""}
        if isinstance(res, list):
            res = res[0] if res else ""
        return {"ok": True, "path": os.path.abspath(res) if res else ""}

    def _reveal(self, payload):
        path = payload.get("path") if isinstance(payload, dict) else None
        if path and os.path.exists(path):
            import subprocess
            try:
                subprocess.Popen(['explorer', f'/select,{os.path.abspath(path)}'])
            except Exception as e:
                return {"ok": False, "error": f"定位文件失败: {e}"}
        return {"ok": True}

    def _open_folder(self, payload):
        path = payload.get("path") if isinstance(payload, dict) else None
        if path and os.path.isdir(path):
            try:
                os.startfile(os.path.abspath(path))
            except Exception as e:
                return {"ok": False, "error": f"打开目录失败: {e}"}
        return {"ok": True}
