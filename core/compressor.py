import os
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

def lossless_compress(input_path, output_dir, format_choice="webp", quality=90, lossless=True):
    try:
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        with Image.open(input_path) as img:
            fmt = format_choice.lower()
            if fmt == "webp":
                out_path = os.path.join(output_dir, f"{base_name}_compressed.webp")
                if lossless:
                    img.save(out_path, "webp", lossless=True, method=6)
                else:
                    img.save(out_path, "webp", quality=quality, method=6, optimize=True)
            elif fmt in ("jpg", "jpeg"):
                out_path = os.path.join(output_dir, f"{base_name}_compressed.jpg")
                img_rgb = img.convert("RGB")
                img_rgb.save(out_path, "jpeg", quality=quality, optimize=True)
            else:
                out_path = os.path.join(output_dir, f"{base_name}_compressed.png")
                img.save(out_path, "png", optimize=True)
        return out_path
    except Exception as e:
        print(f"压缩失败: {e}")
        return None

def analyze_image_file(path):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise Exception(f"无法读取图片: {path}")
    h, w = img.shape[:2]
    has_alpha = len(img.shape) == 3 and img.shape[2] == 4 and np.any(img[:, :, 3] < 255)
    return {"width": w, "height": h, "has_alpha": has_alpha}

def crop_image_file(path, x, y, width, height, out_path, out_ext=".png"):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise Exception(f"无法读取图片: {path}")
    x = max(0, int(x))
    y = max(0, int(y))
    width = max(1, int(width))
    height = max(1, int(height))
    h, w = img.shape[:2]
    x2 = min(w, x + width)
    y2 = min(h, y + height)
    cropped = img[y:y2, x:x2]
    if cropped.size == 0:
        raise Exception("裁切区域无效")
    if out_ext in (".jpg", ".jpeg"):
        ok, buf = cv2.imencode(out_ext, cropped, [cv2.IMWRITE_JPEG_QUALITY, 100])
    elif out_ext == ".webp":
        ok, buf = cv2.imencode(out_ext, cropped, [cv2.IMWRITE_WEBP_QUALITY, 100])
    else:
        ok, buf = cv2.imencode(out_ext, cropped)
    if not ok:
        raise Exception(f"裁切结果编码失败: {out_ext}")
    with open(out_path, "wb") as f:
        f.write(buf.tobytes())
    return out_path
