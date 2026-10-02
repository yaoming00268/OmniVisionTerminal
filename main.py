import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from core.config_manager import load_config
from app.server import WebServer

def _enable_log_file(path):
    """将 print 输出同步写入日志文件(供桌面控制台等外部程序读取)。"""
    try:
        log_f = open(path, "a", encoding="utf-8", buffering=1)
    except OSError as e:
        print(f"无法写入日志文件 {path}: {e}")
        return
    original_stdout = sys.stdout

    class Tee:
        def write(self, data):
            try:
                original_stdout.write(data)
            except Exception:
                pass
            try:
                log_f.write(data)
                log_f.flush()
            except Exception:
                pass

        def flush(self):
            try:
                original_stdout.flush()
            except Exception:
                pass
            try:
                log_f.flush()
            except Exception:
                pass

    sys.stdout = Tee()
    print(f"运行日志将写入: {path}")

def _trace(msg):
    """诊断打点: 写入引擎目录 desktop_trace.log(正式版无副作用)。"""
    try:
        with open(os.path.join(PROJECT_ROOT, "desktop_trace.log"), "a",
                  encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _run_desktop(secondary=False):
    """桌面窗口模式: 直接调用 Python 逻辑, 不启动任何 HTTP 服务。"""
    _trace("step1 import desktop_api")
    from desktop_api import DesktopApi
    from app.api import AppState
    from monitor_utils import window_pos
    _trace("step2 import webview")
    import webview
    _trace("step3 create state")
    state = AppState()
    api = DesktopApi(state)
    index = os.path.join(PROJECT_ROOT, "web", "index.html")
    wargs = dict(width=1280, height=840, min_size=(960, 640))
    if secondary:
        x, y = window_pos(1280, 840, secondary=True)
        wargs["x"], wargs["y"] = x, y
    _trace("step4 create_window")
    win = webview.create_window(
        "全能视像解析终端 - 桌面版",
        url=index, js_api=api, **wargs,
    )
    api.set_window(win)
    _trace("step5 webview.start")
    webview.start()
    _trace("step6 started")


def main():
    parser = argparse.ArgumentParser(
        prog="vision-terminal",
        description="全能视像解析终端 Web 版 — 轻量标准库 HTTP 服务器 + WeUI 风格前端",
    )
    parser.add_argument("--port", type=int, default=None, help="监听端口(默认读取配置 webui_port)")
    parser.add_argument("--server-name", default=None, help="监听地址(默认读取配置 webui_server_name)")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    parser.add_argument("--desktop", action="store_true",
                        help="以桌面窗口模式启动(不启动 HTTP 服务, 直接打开独立界面)")
    parser.add_argument("--secondary", action="store_true",
                        help="桌面窗口显示在副显示屏(调试用)")
    parser.add_argument("--log-file", default=None, help="将运行日志同时追加写入指定文件")
    args = parser.parse_args()

    if args.log_file:
        _enable_log_file(args.log_file)

    if args.desktop:
        _run_desktop(args.secondary)
        return

    config = load_config()
    port = args.port or int(config.get("webui_port", 7860))
    default_host = "0.0.0.0" if config.get("webui_share") else "127.0.0.1"
    server_name = args.server_name or config.get("webui_server_name", default_host)
    if config.get("webui_share") and server_name in ("0.0.0.0", "::"):
        print("提示: 已启用局域网共享模式 (webui_share)，其他设备可通过本机局域网 IP 访问。")
    print("正在加载核心组件(PyTorch / OpenCV / 模型引擎)...")
    try:
        WebServer(port=port, server_name=server_name, open_browser=not args.no_browser).run()
    except Exception:
        import traceback
        print(traceback.format_exc())
        raise

if __name__ == "__main__":
    main()
