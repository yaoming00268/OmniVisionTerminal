import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(PROJECT_ROOT, "models")

def get_model_descs():
    return {
        "pro-no-denoise-up2x": "Real-CUGAN 2x 无降噪版。适合原本清晰、无噪点的图像。",
        "pro-no-denoise-up3x": "Real-CUGAN 3x 无降噪版。适合原本清晰、无噪点的图像放大。",
        "pro-conservative-up2x": "Real-CUGAN 2x 保守版。保留原图质感，相对安全。",
        "pro-conservative-up3x": "Real-CUGAN 3x 保守版。保留原图质感。",
        "pro-denoise3x-up2x": "Real-CUGAN 2x 强降噪版。适合画质差、有马赛克的图像。",
        "pro-denoise3x-up3x": "Real-CUGAN 3x 强降噪版。高强度去噪加放大。",
        "HAT_x4": "HAT 4x。算力需求高，完美还原真实风景细节。",
        "anime_6B": "RealESRGAN 二次元泛用模型。处理速度快，适合动漫图像。",
        "realesr-animevideov3": "RealESRGAN 极速二次元模型。处理视频或大量图像流的首选。",
        "x4plus": "RealESRGAN 三次元真实世界模型。细节生成激进，适合真实照片。",
        "RealESRNet_x4plus": "RealESRGAN 平滑版三次元模型。去除了激进强化，画面自然。",
        "RealESRGANv2-animevideo-xsx2": "RealESRGANv2 极小巧视频模型 2x。极速，占用显存极小，适合低配显卡。",
        "RealESRGANv2-animevideo-xsx4": "RealESRGANv2 极小巧视频模型 4x。极速，占用显存极小，适合低配显卡。"
    }

def get_model_urls():
    return {
        "pro-no-denoise-up2x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up2x-latest-no-denoise.pth",
        "pro-no-denoise-up3x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up3x-latest-no-denoise.pth",
        "pro-conservative-up2x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up2x-latest-conservative.pth",
        "pro-conservative-up3x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up3x-latest-conservative.pth",
        "pro-denoise3x-up2x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up2x-latest-denoise3x.pth",
        "pro-denoise3x-up3x": "https://huggingface.co/JacksonYan/Real-CUGAN/resolve/main/weights/up3x-latest-denoise3x.pth",
        "HAT_x4": "https://huggingface.co/Acly/hat/resolve/main/HAT_SRx4_ImageNet-pretrain.pth",
        "anime_6B": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "realesr-animevideov3": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
        "x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "RealESRNet_x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
        "RealESRGANv2-animevideo-xsx2": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.3.0/RealESRGANv2-animevideo-xsx2.pth",
        "RealESRGANv2-animevideo-xsx4": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.3.0/RealESRGANv2-animevideo-xsx4.pth"
    }

# ---------- 模型库管理(内置 + 本地导入) ----------

def _safe_name(name):
    """净化模型名, 防止路径穿越。"""
    base = os.path.basename(str(name or "").strip())
    if not base or base in (".", ".."):
        raise ValueError("无效的模型名称")
    if any(c in base for c in '/\\:'):
        raise ValueError("模型名称包含非法字符")
    return base

def list_model_library():
    """返回模型库列表: 内置模型 + models/ 目录下的本地模型。"""
    descs = get_model_descs()
    builtin = [{"name": k, "desc": v, "builtin": True, "size": None}
               for k, v in descs.items()]
    local = []
    if os.path.isdir(MODEL_DIR):
        try:
            entries = sorted(os.listdir(MODEL_DIR))
        except OSError:
            entries = []
        for f in entries:
            if f.lower().endswith(".pth") and f[:-4] not in descs:
                try:
                    size = os.path.getsize(os.path.join(MODEL_DIR, f))
                except OSError:
                    size = 0
                local.append({"name": f[:-4], "desc": "本地导入模型", "builtin": False, "size": size})
    return builtin + local

def rename_model(old_name, new_name):
    old_name = _safe_name(old_name)
    new_name = _safe_name(new_name)
    if old_name in get_model_descs():
        raise ValueError("内置模型不可重命名")
    if new_name in get_model_descs():
        raise ValueError("新名称与内置模型冲突")
    src = os.path.join(MODEL_DIR, old_name + ".pth")
    dst = os.path.join(MODEL_DIR, new_name + ".pth")
    if not os.path.isfile(src):
        raise ValueError("模型文件不存在")
    if os.path.exists(dst):
        raise ValueError("目标名称已存在")
    os.rename(src, dst)

def delete_model(name):
    name = _safe_name(name)
    if name in get_model_descs():
        raise ValueError("内置模型不可删除")
    path = os.path.join(MODEL_DIR, name + ".pth")
    if os.path.isfile(path):
        os.remove(path)

def import_model_file(filename, data_bytes):
    filename = _safe_name(filename)
    if not filename.lower().endswith(".pth"):
        raise ValueError("仅支持 .pth 模型文件")
    if filename[:-4] in get_model_descs():
        raise ValueError("该名称与内置模型冲突")
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, filename)
    with open(path, "wb") as f:
        f.write(data_bytes)
    return filename[:-4]
