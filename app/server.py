import os
import sys
import json
import mimetypes
import threading
import webbrowser
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_ROOT = os.path.join(PROJECT_ROOT, "web")
sys.path.insert(0, PROJECT_ROOT)

from app import api

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json",
}

class WebHandler(BaseHTTPRequestHandler):
    server_version = "VisionTerminal/2.0"
    protocol_version = "HTTP/1.1"

    # ---- 基础设施 ----
    def log_message(self, fmt, *args):
        pass

    @property
    def state(self):
        return self.server.app_state

    def _send(self, status, ctype, body, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file_stream(self, status, ctype, file_path, headers=None):
        """流式分块发送大文件，避免将整个文件读入内存。"""
        _CHUNK = 1024 * 1024  # 1 MB
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            self._send_json(404, {"error": "文件不存在"})
            return
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(_CHUNK)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_json(self, status, obj):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _check_auth(self):
        auth_user = self.state.config.get("webui_auth_user", "")
        auth_pwd = self.state.config.get("webui_auth_pwd", "")
        if not auth_user and not auth_pwd:
            return True
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return False
        import base64
        try:
            raw = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            user, _, pwd = raw.partition(":")
            return user == auth_user and pwd == auth_pwd
        except Exception:
            return False

    # ---- 请求分发 ----
    def _dispatch(self, body=b""):
        if not self._check_auth():
            self._send(401, "application/json; charset=utf-8",
                       b'{"error":"Unauthorized"}',
                       {"WWW-Authenticate": 'Basic realm="VisionTerminal"'})
            return

        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path.startswith("/api/"):
            self._dispatch_api(path, query, body)

        elif self.command == "GET" and (path == "/" or path == "/index.html"):
            self._serve_static("index.html")
        elif self.command == "GET" and path.startswith("/static/"):
            rel = path[len("/static/"):]
            self._serve_static(os.path.join("static", rel))
        else:
            self._send_json(404, {"error": "Not Found"})

    def _dispatch_api(self, path, query, body):
        route = path[len("/api/"):]
        state = self.state

        # 通用 GET/POST 路由表
        if route == "config" and self.command == "GET":
            self._emit(api.api_get_config(state))
        elif route == "config" and self.command == "POST":
            self._emit(api.api_post_config(state, body))
        elif route == "models":
            self._emit(api.api_get_models(state))
        elif route == "model_library":
            self._emit(api.api_get_model_library(state))
        elif route == "model/rename":
            self._emit(api.api_post_model_rename(state, body))
        elif route == "model/delete":
            self._emit(api.api_post_model_delete(state, body))
        elif route == "model/import":
            form = self._parse_multipart(body) if self._is_multipart() else []
            self._emit(api.api_post_model_import(state, form))
        elif route == "model/order":
            self._emit(api.api_post_model_order(state, body))
        elif route == "queue" and self.command == "GET":
            self._emit(api.api_get_queue(state))
        elif route == "queue" and self.command == "POST":
            if self._is_multipart():
                form = self._parse_multipart(body)
                self._emit(api.api_post_queue(state, form))
            else:
                self._emit(api.api_post_queue(state, None, body))
        elif route == "queue" and self.command == "DELETE":
            self._emit(api.api_delete_queue(state, query))
        elif route == "job/start":
            self._emit(api.api_post_job_start(state, body))
        elif route == "job/status":
            self._emit(api.api_get_job_status(state, query))
        elif route == "job/control":
            self._emit(api.api_post_job_control(state, body))
        elif route.startswith("file/"):
            self._emit(api.api_get_file(state, route[len("file/"):], query=query))
        elif route.startswith("output/"):
            self._emit(api.api_get_output(state, route[len("output/"):]))
        elif route.startswith("preview/"):
            self._emit(api.api_get_preview(state, route[len("preview/"):]))
        elif route == "open_dir":
            self._emit(api.api_post_open_dir(state, body))
        elif route == "inspect":
            self._emit(api.api_get_inspect(state, query))
        elif route == "dir_list":
            self._emit(api.api_get_dir_list(state, query))
        elif route == "crop":
            self._emit(api.api_post_crop(state, body))
        elif route == "hardware":
            self._emit(api.api_post_hardware(state, body))
        elif route == "autotune":
            self._emit(api.api_post_autotune(state))
        elif route == "compress":
            self._emit(api.api_post_compress(state, body))
        elif route == "package":
            self._emit(api.api_post_package(state))
        elif route == "bg" and self.command == "POST":
            form = self._parse_multipart(body) if self._is_multipart() else []
            self._emit(api.api_post_bg(state, form))
        elif route == "bg" and self.command == "GET":
            self._emit(api.api_get_bg(state))
        else:
            self._send_json(404, {"error": "未知接口"})

    def _emit(self, result):
        if len(result) == 5:
            # 5元组: (status, ctype, body_or_None, headers, file_path) — 触发流式发送
            status, ctype, _, headers, file_path = result
            self._send_file_stream(status, ctype, file_path, headers)
        else:
            status, ctype, body, headers = result
            self._send(status, ctype, body, headers)

    # ---- 静态文件 ----
    def _serve_static(self, rel):
        full = os.path.normpath(os.path.join(WEB_ROOT, rel))
        if not full.startswith(WEB_ROOT) or not os.path.isfile(full):
            self._send_json(404, {"error": "静态资源不存在"})
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = STATIC_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if ext in (".html", ".js", ".css") else "max-age=3600")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---- multipart 解析 ----
    def _is_multipart(self):
        ctype = self.headers.get("Content-Type", "")
        return ctype.startswith("multipart/form-data")

    def _parse_multipart(self, body):
        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            return []
        boundary = ctype.split("boundary=", 1)[1].strip().strip('"').encode("utf-8")
        delim = b"--" + boundary
        parts = []
        for raw_part in body.split(delim):
            raw_part = raw_part.strip(b"\r\n")
            if not raw_part or raw_part == b"--":
                continue
            header_blob, _, content = raw_part.partition(b"\r\n\r\n")
            headers = {}
            for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    headers[k.strip().lower()] = v.strip()
            disp = headers.get("content-disposition", "")
            field = ""
            filename = ""
            for seg in disp.split(";"):
                seg = seg.strip()
                if seg.startswith("name="):
                    field = seg[5:].strip('"')
                elif seg.startswith("filename="):
                    filename = seg[9:].strip('"')
            if content.endswith(b"\r\n"):
                content = content[:-2]
            parts.append((field, filename, content))
        return parts

    # ---- HTTP 方法 ----
    def do_GET(self):
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send_json(500, {"error": str(e)})
            except Exception:
                pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        try:
            self._dispatch(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send_json(500, {"error": str(e)})
            except Exception:
                pass

    def do_DELETE(self):
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send_json(500, {"error": str(e)})
            except Exception:
                pass

class WebServer:
    def __init__(self, port=7860, server_name="0.0.0.0", open_browser=True):
        self.port = int(port)
        self.server_name = server_name
        self.open_browser = open_browser
        self.httpd = None
        self.app_state = api.AppState()

    def run(self):
        port = self.port
        last_err = None
        for offset in range(21):
            try:
                self.httpd = ThreadingHTTPServer((self.server_name, port + offset), WebHandler)
                self.port = port + offset
                break
            except OSError as e:
                last_err = e
                continue
        if self.httpd is None:
            raise RuntimeError(f"无法启动服务器 (端口 {port}..{port + 20}): {last_err}")
        self.httpd.app_state = self.app_state
        self.httpd.daemon_threads = True
        url = f"http://127.0.0.1:{self.port}/"
        print(f"全能视像解析终端 Web 服务已启动: {url}")
        print("按 Ctrl+C 停止服务。")
        if self.open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务已停止。")
        finally:
            self.httpd.server_close()
