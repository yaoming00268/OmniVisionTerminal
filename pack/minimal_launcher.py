# minimal_launcher.py — 二分实验 B: 内联完整 launcher_pwv 逻辑(除 monitor_utils)
import os
import sys
import json
import subprocess
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _paths():
    base = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(base) == "_internal":
        root = os.path.dirname(base)
        appdir = os.path.dirname(root)
        engine = os.path.join(appdir, "PhantomCore", "PhantomCore.exe")
        return {
            "engine": engine,
            "engine_dir": os.path.dirname(engine),
            "config": os.path.join(appdir, "PhantomCore", "upscale_config.json"),
        }
    return {
        "engine": os.path.join(base, "PhantomCore.exe"),
        "engine_dir": base,
        "config": os.path.join(base, "upscale_config.json"),
    }


def _config_path():
    return _paths()["config"]


def _read_mode():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            return (json.load(f).get("launcher_default_mode") or "ask")
    except Exception:
        return "ask"


class LauncherApi:
    def __init__(self):
        self._leaving = False
        self.window = None

    def launch(self, mode):
        mode = str(mode or "webui")
        p = _paths()
        args = [p["engine"]]
        if mode == "desktop":
            args.append("--desktop")
        elif mode == "service":
            args.append("--no-browser")
        try:
            subprocess.Popen(args, cwd=p["engine_dir"])
        except OSError as e:
            self._schedule_quit(1.0)
            return {"ok": False, "error": "start fail: %s" % e}
        self._schedule_quit(0.8)
        return {"ok": True, "mode": mode}

    def remember_mode(self, mode):
        mode = str(mode or "ask")
        try:
            with open(_config_path(), encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg["launcher_default_mode"] = mode
        tmp = _config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _config_path())
        return {"ok": True, "mode": mode}

    def open_data_dir(self):
        try:
            os.startfile(_paths()["engine_dir"])
        except OSError:
            pass
        return {"ok": True}

    def quit_app(self):
        self._schedule_quit(0.05)
        return {"ok": True}

    def _schedule_quit(self, delay):
        if self._leaving:
            return
        self._leaving = True
        threading.Timer(delay, self._do_quit).start()

    def _do_quit(self):
        win = getattr(self, "window", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        threading.Timer(1.2, os._exit, args=(0,)).start()


def main():
    mode = _read_mode()
    if mode in ("desktop", "webui", "service"):
        LauncherApi().launch(mode)
        return
    import webview
    api = LauncherApi()
    index = os.path.join(BASE, "web", "launcher.html")
    wargs = dict(width=760, height=600, resizable=False)
    win = webview.create_window(
        "全能视像解析终端",
        url=index, js_api=api, **wargs,
    )
    # 注意: 不把窗口对象赋给 js_api 属性(避免桥接序列化问题)
    webview.start()


if __name__ == "__main__":
    main()
