import os
import shutil
import subprocess

def get_ffmpeg_exe():
    """定位可用的 ffmpeg 可执行文件:环境变量 -> 系统 PATH -> imageio_ffmpeg 自带二进制。"""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    path_bin = shutil.which("ffmpeg")
    if path_bin:
        return path_bin
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and os.path.exists(bundled):
            return bundled
    except Exception:
        pass
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg", "ffmpeg.exe")
    if os.path.exists(local):
        return local
    return "ffmpeg"

def run_ffmpeg(args, check=False):
    exe = get_ffmpeg_exe()
    cmd = [exe] + args
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=check, creationflags=creationflags)

def download_model_if_needed(model_name, model_dir="models", log_callback=None):
    import requests
    from core.models import get_model_urls
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, f"{model_name}.pth")
    if os.path.exists(model_path):
        return model_path
    urls = get_model_urls()
    url = urls.get(model_name)
    if not url:
        raise Exception(f"未找到模型 {model_name} 的下载链接")
    if log_callback:
        log_callback(f"开始下载模型权重: {model_name}...")
    # 显式控制代理: 不读系统代理(可能失效), 依次尝试直连与常见本地代理端口
    session = requests.Session()
    session.trust_env = False
    proxy_ports = [None, 7890, 10809, 1080, 8080, 1081, 2334]
    last_exception = None
    for port in proxy_ports:
        proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"} if port else None
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = session.get(url, stream=True, headers=headers, timeout=30, proxies=proxies)
            response.raise_for_status()
            with open(model_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            if os.path.getsize(model_path) < 5 * 1024 * 1024:
                try:
                    os.remove(model_path)
                except OSError as err:
                    if log_callback:
                        log_callback(f"清理异常模型文件失败: {err}")
                raise Exception("下载文件体积异常 (小于5MB)，可能为网络拦截页面或损坏文件")
            if log_callback:
                log_callback("模型下载完成")
            return model_path
        except Exception as e:
            last_exception = e
            if os.path.exists(model_path):
                try:
                    os.remove(model_path)
                except OSError as err:
                    if log_callback:
                        log_callback(f"清理异常模型文件失败: {err}")
    try:
        session.close()
    except Exception:
        pass
    raise Exception(f"模型拉取失败，已耗尽所有代理路线: {last_exception}")

def apply_letterbox_core(img_array, target_w, target_h, force_custom_res, is_alpha=False):
    import cv2
    import numpy as np
    if not force_custom_res:
        return img_array
    h, w = img_array.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    if new_w <= 0 or new_h <= 0:
        return img_array
    resized_img = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    if is_alpha or len(img_array.shape) == 2:
        canvas = np.zeros((target_h, target_w), dtype=np.uint8)
    else:
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    y_offset = (target_h - new_h) // 2
    x_offset = (target_w - new_w) // 2
    canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_img
    return canvas

VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".mpg", ".mpeg", ".m4v", ".ts", ".vob", ".3gp")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

def is_video_file(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS

def read_image_rgb(path):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise Exception(f"无法读取图像文件: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

def encode_image(img_rgb, out_ext=".png", quality=100):
    import cv2
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    if out_ext == ".webp":
        ok, buf = cv2.imencode(out_ext, img_bgr, [cv2.IMWRITE_WEBP_QUALITY, quality])
    elif out_ext in (".jpg", ".jpeg"):
        ok, buf = cv2.imencode(out_ext, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    else:
        ok, buf = cv2.imencode(out_ext, img_bgr)
    if not ok:
        raise Exception(f"图像编码失败: {out_ext}")
    return buf.tobytes()
