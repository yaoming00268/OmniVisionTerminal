import os
import shutil
import subprocess
import tempfile
import cv2
import numpy as np
from core.upscaler import core_upscale
from core.utils import apply_letterbox_core, run_ffmpeg, get_ffmpeg_exe

def process_video_core(video_path, model, native_scale, device, scale_factor=4.0, block_size=1000,
                       use_fast_mode=False, video_mode="upscale_only", interp_ratio=2, force_custom=False,
                       target_w=1920, target_h=1080, output_dir=None, temp_workspace_dir=None,
                       progress_callback=None, throttle_callback=None, out_format=".mp4",
                       check_control=None):
    out_dir = output_dir if output_dir else os.path.dirname(video_path)
    os.makedirs(out_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    
    if not out_format:
        out_format = ".mp4"
    if not out_format.startswith("."):
        out_format = f".{out_format}"
    out_format = out_format.lower()
    out_path = os.path.join(out_dir, f"{base_name}_enhanced{out_format}")

    do_upscale = video_mode in ["upscale_only", "both"]
    do_interp = video_mode in ["interp_only", "both"]

    cap = cv2.VideoCapture(video_path)
    original_fps = cap.get(cv2.CAP_PROP_FPS)
    if original_fps <= 0:
        original_fps = 24.0
    cap.release()

    target_fps = original_fps * interp_ratio if do_interp else original_fps

    base_workspace = temp_workspace_dir if temp_workspace_dir else tempfile.gettempdir()
    temp_dir_in = os.path.join(base_workspace, f"{base_name}_frames_in")
    os.makedirs(temp_dir_in, exist_ok=True)
    audio_path = os.path.join(base_workspace, f"{base_name}_audio.aac")

    if progress_callback:
        progress_callback("正在分离视频音频与时间轴帧数据...", 0)

    run_ffmpeg(["-y", "-i", video_path, "-vn", "-c:a", "aac", audio_path])
    has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0

    # 使用最高质量的 JPEG 参数 (-q:v 1) 提取帧，显著降低二次压缩损失
    run_ffmpeg(["-y", "-i", video_path, "-vsync", "0", "-q:v", "1",
                os.path.join(temp_dir_in, "frame_%08d.jpg")], check=True)

    frame_files_in = sorted([f for f in os.listdir(temp_dir_in) if f.endswith(".jpg")])
    total_frames = len(frame_files_in)

    if progress_callback:
        progress_callback("初始化视频滚动重构数据流...", 5)

    encoder = "h264_nvenc" if device.type == "cuda" else "libx264"
    merge_cmd = ["-y", "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(target_fps), "-i", "-"]
    if has_audio:
        merge_cmd.extend(["-i", audio_path, "-map", "0:v", "-map", "1:a", "-c:a", "copy"])
    else:
        merge_cmd.extend(["-map", "0:v"])
    merge_cmd.extend(["-c:v", encoder, "-pix_fmt", "yuv420p", "-b:v", "10M", out_path])

    exe = get_ffmpeg_exe()
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    ffmpeg_proc = subprocess.Popen([exe] + merge_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=creationflags)

    prev_frame_out = None

    try:
        for i, frame_name in enumerate(frame_files_in):
            if check_control:
                check_control()
            in_frame_path = os.path.join(temp_dir_in, frame_name)
            if throttle_callback:
                throttle_callback()
            frame_bgr = cv2.imdecode(np.fromfile(in_frame_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            if do_upscale:
                h, w = frame_rgb.shape[:2]
                current_frame = core_upscale(frame_rgb, model, native_scale, device, block_size,
                                             use_fast_mode, slice_save_dir=None, check_control=check_control)
                if scale_factor != native_scale:
                    new_w = max(1, int(round(w * scale_factor)))
                    new_h = max(1, int(round(h * scale_factor)))
                    current_frame = cv2.resize(current_frame, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            else:
                current_frame = frame_rgb
            current_frame = apply_letterbox_core(current_frame, target_w, target_h, force_custom, False)
            frames_to_write = []
            if do_interp and prev_frame_out is not None:
                # 注意: 此处为轻量级线性加权插帧 (cv2.addWeighted)，适用于低帧率静态/缓动镜头。
                # 剧烈运动场景易产生重影 (ghosting)，建议根据需要后续升级至光流插帧算法 (如 RIFE)。
                for j in range(1, int(interp_ratio)):
                    alpha = j / interp_ratio
                    interp_frame = cv2.addWeighted(prev_frame_out, 1 - alpha, current_frame, alpha, 0)
                    frames_to_write.append(interp_frame)
            frames_to_write.append(current_frame)
            for frm in frames_to_write:
                frm_bgr = cv2.cvtColor(frm, cv2.COLOR_RGB2BGR)
                ok, enc = cv2.imencode(".jpg", frm_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ok:
                    try:
                        ffmpeg_proc.stdin.write(enc.tobytes())
                    except (BrokenPipeError, OSError) as e:
                        raise RuntimeError(f"FFmpeg 写入管道破裂，请检查显卡驱动或编码器配置: {e}")
            try:
                os.remove(in_frame_path)
            except OSError:
                pass
            prev_frame_out = current_frame
            if progress_callback:
                pct = 5 + int(((i + 1) / total_frames) * 93)
                if (i + 1) % max(1, int(original_fps)) == 0:
                    progress_callback(f"滚动渲染中: {i + 1}/{total_frames} 帧", pct)
    finally:
        if ffmpeg_proc:
            if ffmpeg_proc.stdin:
                try:
                    ffmpeg_proc.stdin.close()
                except Exception:
                    pass
            try:
                ffmpeg_proc.wait(timeout=1)
            except Exception:
                try:
                    ffmpeg_proc.kill()
                except Exception:
                    pass
        shutil.rmtree(temp_dir_in, ignore_errors=True)
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass

    if progress_callback:
        progress_callback("视频重构完毕", 100)
    return out_path
