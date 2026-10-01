# desktop.py — 桌面版(pywebview 独立窗口)入口
# 不启动任何 HTTP 服务: 前端通过 js_api 直接调用 Python 逻辑。
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def main():
    from desktop_api import DesktopApi
    from app.api import AppState
    import webview

    state = AppState()
    api = DesktopApi(state)
    index = os.path.join(BASE, "web", "index.html")
    win = webview.create_window(
        "全能视像解析终端 - 桌面版",
        url=index, js_api=api,
        width=1280, height=840, min_size=(960, 640),
    )
    api.set_window(win)
    webview.start()


if __name__ == "__main__":
    main()
