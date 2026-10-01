# launcher_pwv.py — 启动器(pywebview 现代化界面)入口
# 三种打开方式: 桌面窗口 / WebUI 浏览器 / 仅后台服务。
# 启动器只负责打开对应模式并立即退出, 不检测/不管理引擎状态。
# launcher_default_mode 配置为 desktop|webui|service 时直接启动对应模式并退出。
import os
import sys
import json
import subprocess
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 窗口引用放在模块级(不能挂到 js_api 实例属性上: pywebview 桥接会遍历
# api 对象属性, 持有窗口对象会导致初始化卡死/未响应)。
_WIN = {"win": None}


def _paths():
    """返回统一引擎执行指令、工作目录与配置路径。
    自动适配：
    1. 源码/脚本运行环境（优先通过 Python 解释器直接运行同目录的 main.py）
    2. 编译打包版（寻找 PhantomCore.exe 独立二进制）
    """
    base = os.path.dirname(os.path.abspath(__file__))
    is_frozen = getattr(sys, "frozen", False)
    is_internal = (os.path.basename(base) == "_internal")

    # 1. 若处于源码运行环境（非 PyInstaller 打包环境），优先同级 main.py
    if not is_frozen and not is_internal:
        main_py = os.path.join(base, "main.py")
        if os.path.isfile(main_py):
            engine_dir = base
            python_candidates = [
                os.path.join(engine_dir, ".venv", "Scripts", "python.exe"),
                sys.executable,
                os.path.join(engine_dir, "python.exe"),
            ]
            py_exe = None
            for cand in python_candidates:
                if cand and os.path.isfile(cand):
                    py_exe = cand
                    break
            if not py_exe:
                py_exe = sys.executable

            py_dir = os.path.dirname(py_exe)
            pyw_exe = os.path.join(py_dir, "pythonw.exe")
            if not os.path.isfile(pyw_exe):
                pyw_exe = py_exe

            cfg = os.path.join(engine_dir, "upscale_config.json")
            return {
                "type": "python",
                "script": main_py,
                "py_exe": py_exe,
                "pyw_exe": pyw_exe,
                "cmd_base": [py_exe, main_py],
                "engine_dir": engine_dir,
                "config": cfg,
            }

    # 2. 打包环境或已编译独立二进制：搜索 PhantomCore.exe
    if is_internal:
        launcher_root = os.path.dirname(base)
        appdir = os.path.dirname(launcher_root)
    elif is_frozen:
        launcher_root = os.path.dirname(sys.executable)
        appdir = os.path.dirname(launcher_root)
    else:
        launcher_root = base
        appdir = base

    exe_candidates = [
        os.path.join(appdir, "PhantomCore", "PhantomCore.exe"),
        os.path.join(launcher_root, "PhantomCore.exe"),
        os.path.join(launcher_root, "PhantomCore", "PhantomCore.exe"),
        os.path.join(base, "PhantomCore.exe"),
        os.path.join(base, "dist", "PhantomCore", "PhantomCore.exe"),
    ]
    for exe in exe_candidates:
        if os.path.isfile(exe):
            engine_dir = os.path.dirname(exe)
            cfg = os.path.join(engine_dir, "upscale_config.json")
            if not os.path.isfile(cfg) and os.path.isfile(os.path.join(base, "upscale_config.json")):
                cfg = os.path.join(base, "upscale_config.json")
            return {
                "type": "exe",
                "cmd_base": [exe],
                "engine_dir": engine_dir,
                "config": cfg,
            }

    # 3. 兜底寻找任意 main.py
    for cand_dir in [base, launcher_root, appdir]:
        cand_main = os.path.join(cand_dir, "main.py")
        if os.path.isfile(cand_main):
            return {
                "type": "python",
                "script": cand_main,
                "py_exe": sys.executable,
                "pyw_exe": sys.executable,
                "cmd_base": [sys.executable, cand_main],
                "engine_dir": cand_dir,
                "config": os.path.join(cand_dir, "upscale_config.json"),
            }

    return {
        "type": "fallback",
        "script": os.path.join(base, "main.py"),
        "py_exe": sys.executable,
        "pyw_exe": sys.executable,
        "cmd_base": [sys.executable, os.path.join(base, "main.py")],
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
        """启动统一引擎的对应模式, 随后自动退出启动器(多开: 每次启动互不影响)。"""
        mode = str(mode or "webui")
        p = _paths()

        if p["type"] == "exe":
            args = list(p["cmd_base"])
            if mode == "desktop":
                args.append("--desktop")
            elif mode == "service":
                args.append("--no-browser")
        else:
            # 源码/脚本模式：根据模式选择最适合的 python 解释器
            # desktop 与 service 模式使用 pythonw.exe 避免多余的黑框控制台
            # webui 模式使用 python.exe 以便展示运行日志及端口状态
            chosen_py = p.get("pyw_exe") if mode in ("desktop", "service") else p.get("py_exe")
            if not chosen_py:
                chosen_py = sys.executable
            args = [chosen_py, p["script"]]
            if mode == "desktop":
                args.append("--desktop")
            elif mode == "service":
                args.append("--no-browser")

        try:
            cflags = 0
            if sys.platform == "win32":
                cflags = subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(args, cwd=p["engine_dir"], creationflags=cflags)
        except OSError as e:
            # 启动失败时切勿退出启动器，以便用户查阅错误并重试
            return {"ok": False, "error": "启动失败: %s" % e}
        self._schedule_quit(0.8)   # 启动成功后自动退出
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
        win = _WIN.get("win")
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        # 兜底: 窗口销毁未生效时强制退出, 避免启动器残留
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
    try:
        from monitor_utils import window_pos
        x, y = window_pos(760, 600)
        wargs["x"], wargs["y"] = x, y
    except Exception:
        pass
    win = webview.create_window(
        "全能视像解析终端",
        url=index, js_api=api, **wargs,
    )
    _WIN["win"] = win
    webview.start()


if __name__ == "__main__":
    main()
