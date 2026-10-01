import os
import threading
import time
import psutil

class SilentManager:
    """静默运行模式: 后台监控系统负载, 动态抑制运算节流。"""
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self.throttle_sleep = 0.0
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # 仅降低当前工作线程的调度优先级，不影响 HTTP Server / UI 主线程
        try:
            if os.name == "nt":
                import ctypes
                THREAD_PRIORITY_IDLE = -15
                handle = ctypes.windll.kernel32.GetCurrentThread()
                ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_PRIORITY_IDLE)
            else:
                import threading
                tid = threading.get_ident()
                # Linux/macOS: 对当前线程 nice 值（近似）
                try:
                    os.nice(10)  # 相对提高 nice 值降低优先级
                except AttributeError:
                    pass
        except Exception:
            pass
        while not self._stop_event.is_set():
            cpu_usage = psutil.cpu_percent(interval=1.0)
            mem_usage = psutil.virtual_memory().percent
            if cpu_usage > 90 or mem_usage > 90:
                sleep_val = 0.5
            elif cpu_usage > 75 or mem_usage > 80:
                sleep_val = 0.1
            else:
                sleep_val = 0.0
            with self._lock:
                self.throttle_sleep = sleep_val
            self._stop_event.wait(2)

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def throttle(self):
        with self._lock:
            sleep_val = self.throttle_sleep
        if sleep_val > 0:
            time.sleep(sleep_val)
