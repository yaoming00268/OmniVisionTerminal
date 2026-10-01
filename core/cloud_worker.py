import os
import time
import threading
import requests

class CloudJob:
    """云端处理任务执行器(线程化, 替代原 QThread 版本)。"""
    def __init__(self, file_paths, config, log_callback=None, progress_callback=None,
                 done_callback=None, result_callback=None):
        self.img_paths = list(file_paths)
        self.server_url = config.get("cloud_server_url", "http://127.0.0.1:8000/process")
        self.api_key = config.get("cloud_api_key", "")
        self.output_dir = config.get("output_dir", "")
        self.model_choice = config.get("model_choice", "anime_6B")
        self.scale = config.get("scale", 4.0)
        self._log_cb = log_callback or (lambda msg: None)
        self._progress_cb = progress_callback or (lambda pct: None)
        self._done_cb = done_callback or (lambda: None)
        self._result_cb = result_callback or (lambda path: None)
        self._thread = None
        self._error = None
        self._pause_evt = threading.Event()
        self._stop_evt = threading.Event()

    def pause(self):
        self._pause_evt.set()

    def resume(self):
        self._pause_evt.clear()

    def is_paused(self):
        return self._pause_evt.is_set()

    def stop(self):
        self._stop_evt.set()
        self.resume()

    def is_stopped(self):
        return self._stop_evt.is_set()

    def _wait_if_paused(self):
        while self._pause_evt.is_set():
            if self._stop_evt.is_set() or not self.is_running():
                return
            time.sleep(0.2)

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def run(self):
        total_imgs = len(self.img_paths)
        self._log_cb("已连接至云端处理节点，开始传输任务。")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for idx, file_path in enumerate(self.img_paths):
            if self._stop_evt.is_set():
                self._log_cb("云端任务已被用户中止。")
                break
            self._wait_if_paused()
            if self._stop_evt.is_set():
                self._log_cb("云端任务已被用户中止。")
                break
            self._log_cb(f"[{idx + 1}/{total_imgs}] 正在上传并处理: {os.path.basename(file_path)}")
            try:
                with open(file_path, "rb") as f:
                    files = {"file": f}
                    data = {"model": self.model_choice, "scale": self.scale}
                    response = requests.post(self.server_url, headers=headers, files=files, data=data,
                                         timeout=300, stream=True)
                if response.status_code == 200:
                    current_out_dir = self.output_dir if self.output_dir else os.path.dirname(file_path)
                    os.makedirs(current_out_dir, exist_ok=True)
                    out_name = f"cloud_enhanced_{os.path.basename(file_path)}"
                    out_path = os.path.join(current_out_dir, out_name)
                    # 流式分块写盘，避免将整个云端响应图片读入内存
                    with open(out_path, "wb") as f_out:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                f_out.write(chunk)
                    self._result_cb(out_path)
                    self._log_cb(f"处理成功，文件已保存至: {out_path}")
                else:
                    self._log_cb(f"云端处理失败，服务器状态码: {response.status_code}")
            except Exception as e:
                self._log_cb(f"网络通信异常: {e}")
            if not self._stop_evt.is_set():
                self._progress_cb(int((idx + 1) / total_imgs * 100))
        if not self._stop_evt.is_set():
            self._log_cb("云端队列全部处理完成。")
        self._done_cb()
