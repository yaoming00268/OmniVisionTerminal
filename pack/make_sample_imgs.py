# make_sample_imgs.py — 为 release 便携版生成"示例图片"目录
# 用法: .venv\Scripts\python.exe -X utf8 pack\make_sample_imgs.py
import os
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

OUT = r"G:\chaofen5\pack\assets\示例图片"
os.makedirs(OUT, exist_ok=True)

W, H = 960, 640


def font(size):
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def save(img, name):
    """cv2.imwrite 不支持中文路径, 改用 imencode 写字节。"""
    ok, buf = cv2.imencode(".png", img)
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(buf.tobytes())


# 1. 风景渐变(天空+太阳+远山, 适合观察超分后色彩过渡)
img = np.zeros((H, W, 3), dtype=np.uint8)
for y in range(H):
    t = y / H
    img[y, :, 0] = int(90 + 60 * t)      # B
    img[y, :, 1] = int(140 + 50 * t)     # G
    img[y, :, 2] = int(210 - 40 * t)     # R
sun = np.zeros((H, W), dtype=np.uint8)
cv2.circle(sun, (W // 2, H // 4), 70, 255, -1)
for i in range(1, 40):
    sun = cv2.GaussianBlur(sun, (0, 0), 6)
sun = cv2.GaussianBlur(sun, (0, 0), 3)
img[sun > 30] = np.array([230, 240, 255], dtype=np.uint8)
pts = np.array([[0, H], [W * 0.18, H * 0.62], [W * 0.34, H * 0.80], [W * 0.52, H * 0.55],
                [W * 0.72, H * 0.78], [W, H * 0.60], [W, H]], dtype=np.int32)
cv2.fillPoly(img, [pts], (70, 120, 90))
save(img, "示例1_风景渐变.png")

# 2. 高频细节纹理(适合观察清晰度恢复)
rng = np.random.default_rng(7)
tex = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
img = cv2.resize(tex, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST)
img = cv2.resize(img, (W, H), interpolation=cv2.INTER_NEAREST)
img = cv2.addWeighted(img, 0.9, np.full_like(img, 90), 0.1, 0)
save(img, "示例2_纹理细节.png")

# 3. 色条与圆形(适合裁切与色彩测试)
img = np.zeros((H, W, 3), dtype=np.uint8)
cols = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
        (255, 255, 255), (128, 128, 128)]
bw = W // len(cols)
for i, c in enumerate(cols):
    cv2.rectangle(img, (i * bw, 0), ((i + 1) * bw, H), c, -1)
for r, c in zip((40, 90, 140), ((0, 0, 0), (255, 255, 255), (0, 0, 0))):
    cv2.circle(img, (W // 2, H // 2), r, c, 6)
save(img, "示例3_色条圆形.png")

# 4. 文字清晰度样张(黑白文字+浅色底)
img = np.full((H, W, 3), 245, dtype=np.uint8)
pil = Image.fromarray(img)
dr = ImageDraw.Draw(pil)
lines = ["全能视像解析终端 示例图片", "局部裁切 / 超分放大 / 无损压缩", "处理前请先加入任务队列",
         "支持 PNG JPG WebP BMP TIFF", "放大倍数: 1x - 64x"]
y = 60
for t in lines:
    dr.text((50, y), t, fill=(20, 20, 20), font=font(42))
    y += 110
save(np.array(pil), "示例4_文字样张.png")

total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
print("SAMPLES_OK", OUT, len(os.listdir(OUT)), "files,", round(total / 1024), "KB")
