import os
import time
import threading
import cv2
import numpy as np
from PIL import Image
from core.compressor import lossless_compress
from core.utils import download_model_if_needed, is_video_file
from core.upscaler import core_upscale
from core.video import process_video_core
from core.silent_manager import SilentManager

Image.MAX_IMAGE_PIXELS = None

class JobInterruptedError(Exception):
    """任务被用户主动中止"""
    pass

class BatchUpscaleJob:
    """批处理任务执行器(线程化, 替代原 QThread 版本, 核心逻辑保持一致)。"""
    def __init__(self, file_paths, config, log_callback=None, progress_callback=None,
                 done_callback=None, result_callback=None, image_callback=None):
        import torch
        # 预加载 spandrel(任务线程首次导入会阻塞, 且缺失依赖时希望立即报错)
        from spandrel import ModelLoader  # noqa: F401
        self.img_paths = list(file_paths)
        self.scale = float(config.get("scale", 4.0))
        self.block_size = config.get("block_size", 1000)
        self.keep_slices = config.get("keep_slices", False)
        self.slice_dir = config.get("slice_dir", "")
        self.output_dir = config.get("output_dir", "")
        self.out_format = config.get("output_format", ".png")
        self.use_fast_mode = config.get("use_fast_mode", False)
        self.use_compression = config.get("use_compression", False)
        self.use_cpu_only = config.get("use_cpu", False)
        self.optimize_alpha_channel = config.get("optimize_alpha_channel", False)
        self.model_choice = config.get("model_choice", "anime_6B")
        self.model_dir = "models"
        self.force_custom_res = config.get("force_custom_res", False)
        self.target_w = config.get("target_width", 1920)
        self.target_h = config.get("target_height", 1080)
        self.video_mode = config.get("video_mode", "upscale_only")
        self.interp_ratio = config.get("interp_ratio", 2)
        self.default_video_format = config.get("default_video_format", ".mp4")
        self.silent_mode = config.get("silent_mode", False)
        self.silent_manager = None
        self.current_file_index = 0
        self.total_files = len(self.img_paths)
        self._log_cb = log_callback or (lambda msg: None)
        self._progress_cb = progress_callback or (lambda pct: None)
        self._done_cb = done_callback or (lambda: None)
        self._result_cb = result_callback or (lambda path: None)
        self._image_cb = image_callback or (lambda src, dst: None)
        self._thread = None
        self._error = None
        self._pause_evt = threading.Event()
        self._stop_evt = threading.Event()
        if self.use_cpu_only or not torch.cuda.is_available():
            self.device = torch.device("cpu")
        else:
            self.device = torch.device("cuda")
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision("high")

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

    def check_control(self):
        if self._stop_evt.is_set():
            raise JobInterruptedError("任务已被用户中止。")
        self._wait_if_paused()
        if self._stop_evt.is_set():
            raise JobInterruptedError("任务已被用户中止。")

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def update_overall_progress(self, local_pct):
        if self.total_files > 0:
            overall_pct = int(((self.current_file_index + (local_pct / 100.0)) / self.total_files) * 100)
            self._progress_cb(overall_pct)

    def run(self):
        import torch
        from spandrel import ModelLoader
        if self.silent_mode:
            self.silent_manager = SilentManager()
            self.silent_manager.start()
            self._log_cb("静默模式策略启用，正在实时监控计算机负载，动态抑制运算节流。")
        try:
            model_path = download_model_if_needed(self.model_choice, self.model_dir, self._log_cb)
            device_name = "CPU" if self.device.type == "cpu" else "CUDA"
            self._log_cb(f"加载模型 [{self.model_choice}] 至 {device_name}...")
            try:
                model = ModelLoader().load_from_file(model_path).eval().to(self.device)
            except Exception as e:
                # 兼容自训练简单网络 (SimpleSRModel) 或非 spandrel 标准模型
                if "SimpleSRModel" in str(e) or "UnsupportedModelError" in type(e).__name__ or "Unsupported model" in str(e):
                    try:
                        from core.train_worker import SimpleSRModel
                        m = SimpleSRModel(scale_factor=int(self.scale)).to(self.device)
                        m.load_state_dict(torch.load(model_path, map_location=self.device))
                        model = m.eval()
                    except Exception:
                        raise e
                else:
                    raise e
            if self.device.type == "cuda":
                model = model.half()
            native_scale = getattr(model, "scale", 2)
            for idx, file_path in enumerate(self.img_paths):
                self.check_control()
                self.current_file_index = idx
                self._log_cb(f"[{idx + 1}/{self.total_files}] 正在处理: {os.path.basename(file_path)}")
                self.update_overall_progress(0)
                if is_video_file(file_path):
                    self.process_single_video(file_path, model, native_scale)
                elif self.optimize_alpha_channel:
                    self.process_alpha_image(file_path, model, native_scale)
                else:
                    self.process_base_image(file_path, model, native_scale)
                self.check_control()
                self.update_overall_progress(100)
            if not self._stop_evt.is_set():
                self._log_cb("队列任务全部完成。")
        except JobInterruptedError:
            self._log_cb("任务已被用户中止。")
        except Exception as e:
            self._error = str(e)
            self._log_cb(f"任务严重中断: {e}")
        finally:
            if self.silent_manager:
                self.silent_manager.stop()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if not self._error and not self._stop_evt.is_set():
                self._progress_cb(100)
            self._done_cb()

    def apply_letterbox(self, img_array, is_alpha=False):
        if not self.force_custom_res:
            return img_array
        h, w = img_array.shape[:2]
        scale = min(self.target_w / w, self.target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        if new_w <= 0 or new_h <= 0:
            return img_array
        resized_img = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        if is_alpha or len(img_array.shape) == 2:
            canvas = np.zeros((self.target_h, self.target_w), dtype=np.uint8)
        else:
            canvas = np.zeros((self.target_h, self.target_w, 3), dtype=np.uint8)
        y_offset = (self.target_h - new_h) // 2
        x_offset = (self.target_w - new_w) // 2
        canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_img
        return canvas

    def process_base_image(self, img_path, model, native_scale):
        import torch
        self.check_control()
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self._log_cb(f"读取图片异常跳过: {img_path}")
            return
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        new_w = max(1, int(round(w * self.scale)))
        new_h = max(1, int(round(h * self.scale)))
        target_desc = f"{new_w}x{new_h}"
        if self.force_custom_res:
            target_desc = f"{self.target_w}x{self.target_h} (填充画布, 图像缩放至: {new_w}x{new_h})"
        self._log_cb(f"原片尺寸: {w}x{h} -> 目标尺寸: {target_desc} (放大倍数: {self.scale}x, 原生模型倍率: {native_scale}x)")

        base_name = os.path.splitext(os.path.basename(img_path))[0]
        current_out_dir = self.output_dir if self.output_dir else os.path.dirname(img_path)
        os.makedirs(current_out_dir, exist_ok=True)
        out_ext = self.out_format.lower()
        output_file = os.path.join(current_out_dir, f"{base_name}_enhanced{out_ext}")
        current_slice_dir = self.slice_dir if self.slice_dir else os.path.dirname(img_path)
        work_slice_dir = os.path.join(current_slice_dir, f"{base_name}_slices_temp")
        if self.keep_slices:
            os.makedirs(work_slice_dir, exist_ok=True)
        else:
            work_slice_dir = None
        try:
            if self.silent_manager:
                self.silent_manager.throttle()
            self._log_cb("推理基础 RGB 通道...")

            def sub_upscale_progress(sub_pct):
                local_pct = 5 + int(sub_pct * 0.70)
                self.update_overall_progress(local_pct)

            self.check_control()
            out_img_rgb = core_upscale(img, model, native_scale, self.device, self.block_size,
                                       self.use_fast_mode, work_slice_dir, out_ext,
                                       log_cb=self._log_cb, progress_cb=sub_upscale_progress,
                                       check_control=self.check_control)
            del img  # 推理完成后立即释放原图，不再需要
            self.check_control()
            self.update_overall_progress(78)
            if self.scale != native_scale:
                out_img_rgb = cv2.resize(out_img_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            self.check_control()
            out_img_rgb = self.apply_letterbox(out_img_rgb)
            out_img_bgr = cv2.cvtColor(out_img_rgb, cv2.COLOR_RGB2BGR)
            del out_img_rgb  # 转换完成后释放 RGB 大图
            self.check_control()
            self.update_overall_progress(85)
            self._log_cb("正在编码写入磁盘...")
            if out_ext == ".webp":
                cv2.imencode(out_ext, out_img_bgr, [cv2.IMWRITE_WEBP_QUALITY, 100])[1].tofile(output_file)
            else:
                cv2.imencode(out_ext, out_img_bgr)[1].tofile(output_file)
            del out_img_bgr  # 写盘后释放 BGR 大图
            self.check_control()
            self.update_overall_progress(92)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._error = "显存溢出 (CUDA OOM)"
                self._log_cb("错误：显存溢出。请关闭极速模式或减小切块大小。")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                return
            self._error = str(e)
            raise e
        if self.use_compression and os.path.exists(output_file) and out_ext != ".webp":
            self.check_control()
            self._log_cb("执行无损压缩...")
            comp_path = lossless_compress(output_file, current_out_dir, format_choice="webp", quality=90, lossless=True)
            if comp_path:
                try:
                    os.remove(output_file)
                except OSError:
                    pass
                output_file = comp_path
        self.check_control()
        out_size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
        self._result_cb(output_file)
        self._image_cb(img_path, output_file)
        self._log_cb(f"处理完毕: {output_file} ({out_size_mb:.2f} MB)")

    def process_alpha_image(self, img_path, model, native_scale):
        import torch
        self.check_control()
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            self._log_cb(f"读取图片异常跳过: {img_path}")
            return
        has_alpha = False
        alpha_channel = None
        if len(img.shape) == 3 and img.shape[2] == 4:
            temp_alpha = img[:, :, 3]
            if np.any(temp_alpha < 255):
                has_alpha = True
                alpha_channel = temp_alpha
            else:
                self._log_cb("检测到全不透明通道，优化跳过。")
            img = img[:, :, :3]
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        new_w = max(1, int(round(w * self.scale)))
        new_h = max(1, int(round(h * self.scale)))
        target_desc = f"{new_w}x{new_h}"
        if self.force_custom_res:
            target_desc = f"{self.target_w}x{self.target_h} (填充画布, 图像缩放至: {new_w}x{new_h})"
        self._log_cb(f"原片尺寸: {w}x{h} -> 目标尺寸: {target_desc} (放大倍数: {self.scale}x, 原生模型倍率: {native_scale}x)")

        base_name = os.path.splitext(os.path.basename(img_path))[0]
        current_out_dir = self.output_dir if self.output_dir else os.path.dirname(img_path)
        os.makedirs(current_out_dir, exist_ok=True)
        out_ext = self.out_format.lower()
        if has_alpha and out_ext in (".jpg", ".jpeg"):
            out_ext = ".png"
        output_file = os.path.join(current_out_dir, f"{base_name}_enhanced{out_ext}")
        current_slice_dir = self.slice_dir if self.slice_dir else os.path.dirname(img_path)
        work_slice_dir = os.path.join(current_slice_dir, f"{base_name}_slices_temp")
        if self.keep_slices:
            os.makedirs(work_slice_dir, exist_ok=True)
        else:
            work_slice_dir = None
        try:
            if self.silent_manager:
                self.silent_manager.throttle()

            if has_alpha:
                def rgb_progress(sub_pct):
                    self.update_overall_progress(5 + int(sub_pct * 0.40))
            else:
                def rgb_progress(sub_pct):
                    self.update_overall_progress(5 + int(sub_pct * 0.70))

            self._log_cb("推理立绘 RGB 主通道...")
            self.check_control()
            out_img_rgb = core_upscale(img, model, native_scale, self.device, self.block_size,
                                       self.use_fast_mode, work_slice_dir, out_ext,
                                       log_cb=self._log_cb, progress_cb=rgb_progress,
                                       check_control=self.check_control)
            del img  # 推理完成后立即释放原图
            self.check_control()
            self.update_overall_progress(48 if has_alpha else 78)
            if self.scale != native_scale:
                out_img_rgb = cv2.resize(out_img_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            self.check_control()
            out_img_rgb = self.apply_letterbox(out_img_rgb)
            out_img_bgr = cv2.cvtColor(out_img_rgb, cv2.COLOR_RGB2BGR)
            del out_img_rgb  # 立即释放 RGB 大图，此后只需 BGR
            if has_alpha:
                if self.silent_manager:
                    self.silent_manager.throttle()
                self._log_cb("推理立绘 Alpha 透明通道...")
                alpha_rgb = cv2.cvtColor(alpha_channel, cv2.COLOR_GRAY2RGB)
                del alpha_channel  # 释放原始 alpha 灰度图

                def alpha_progress(sub_pct):
                    self.update_overall_progress(50 + int(sub_pct * 0.38))

                self.check_control()
                out_alpha_rgb = core_upscale(alpha_rgb, model, native_scale, self.device, self.block_size,
                                             self.use_fast_mode, None, out_ext,
                                             log_cb=self._log_cb, progress_cb=alpha_progress,
                                             check_control=self.check_control)
                del alpha_rgb  # 释放三通道 alpha 输入
                self.check_control()
                self.update_overall_progress(88)
                if self.scale != native_scale:
                    out_alpha_rgb = cv2.resize(out_alpha_rgb, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                self.check_control()
                out_alpha_rgb = self.apply_letterbox(out_alpha_rgb, is_alpha=True)
                alpha_resized = (out_alpha_rgb[:, :, 0] if len(out_alpha_rgb.shape) == 3 else out_alpha_rgb).copy()
                del out_alpha_rgb  # 释放 alpha 推理结果
                out_img_bgra = cv2.cvtColor(out_img_bgr, cv2.COLOR_BGR2BGRA)
                del out_img_bgr   # 释放 BGR 大图
                out_img_bgra[:, :, 3] = alpha_resized
                del alpha_resized
                self.check_control()
                self._log_cb("正在编码写入磁盘...")
                cv2.imencode(out_ext, out_img_bgra)[1].tofile(output_file)
                del out_img_bgra
            else:
                self.check_control()
                self._log_cb("正在编码写入磁盘...")
                cv2.imencode(out_ext, out_img_bgr)[1].tofile(output_file)
                del out_img_bgr
            self.check_control()
            self.update_overall_progress(92)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._error = "显存溢出 (CUDA OOM)"
                self._log_cb("显存溢出。请关闭极速模式或减小切块大小。")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                return
            self._error = str(e)
            raise e
        if self.use_compression and os.path.exists(output_file) and out_ext != ".webp":
            self.check_control()
            self._log_cb("执行无损压缩...")
            comp_path = lossless_compress(output_file, current_out_dir, format_choice="webp", quality=90, lossless=True)
            if comp_path:
                try:
                    os.remove(output_file)
                except OSError:
                    pass
                output_file = comp_path
        self.check_control()
        out_size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
        self._result_cb(output_file)
        self._image_cb(img_path, output_file)
        self._log_cb(f"处理完毕: {output_file} ({out_size_mb:.2f} MB)")

    def process_single_video(self, video_path, model, native_scale):
        def progress_cb(msg, local_pct=None):
            if local_pct is not None:
                self.update_overall_progress(local_pct)
            else:
                self._log_cb(msg)

        def throttle_cb():
            if self.silent_manager:
                self.silent_manager.throttle()

        out_path = process_video_core(
            video_path=video_path,
            model=model,
            native_scale=native_scale,
            device=self.device,
            scale_factor=self.scale,
            block_size=self.block_size,
            use_fast_mode=self.use_fast_mode,
            video_mode=self.video_mode,
            interp_ratio=self.interp_ratio,
            force_custom=self.force_custom_res,
            target_w=self.target_w,
            target_h=self.target_h,
            output_dir=self.output_dir,
            temp_workspace_dir=self.slice_dir,
            progress_callback=progress_cb,
            throttle_callback=throttle_cb,
            out_format=self.default_video_format,
            check_control=self.check_control
        )
        self._result_cb(out_path)
        self._log_cb(f"视频输出完毕: {out_path}")
