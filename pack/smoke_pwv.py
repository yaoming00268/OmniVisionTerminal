import threading, time
import webview

def close_later():
    time.sleep(3)
    for w in webview.windows:
        w.destroy()

class Api:
    def ping(self):
        return "pong"

t = threading.Thread(target=close_later, daemon=True)
t.start()
w = webview.create_window("smoke", html="<h1>pywebview ok</h1>", js_api=Api())
webview.start()
print("PYWEBVIEW_SMOKE_OK")
