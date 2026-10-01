# make_release_v240.py — 组装 v2.4.0 便携版并打包 zip
# 用法: .venv\Scripts\python.exe -X utf8 pack\make_release_v240.py
import os
import shutil
import zipfile
import time

ROOT = r"G:\chaofen5"
DIST_APP = os.path.join(ROOT, "pack", "dist", "App")
RELEASE = os.path.join(ROOT, "pack", "release")
NAME = "全能视像解析终端_便携版_v2.4.0"
PORTABLE = os.path.join(RELEASE, NAME)
ZIP = PORTABLE + ".zip"

# 1. 组装 dist\App
if os.path.exists(DIST_APP):
    shutil.rmtree(DIST_APP)
os.makedirs(DIST_APP)
shutil.copytree(os.path.join(ROOT, "pack", "dist", "PhantomCore"),
                os.path.join(DIST_APP, "PhantomCore"))
shutil.copytree(os.path.join(ROOT, "pack", "dist", "PhantomLauncher"),
                os.path.join(DIST_APP, "PhantomLauncher"))
shutil.copytree(os.path.join(ROOT, "pack", "assets", "示例图片"),
                os.path.join(DIST_APP, "示例图片"))
shutil.copy(os.path.join(ROOT, "pack", "assets", "使用说明.txt"),
            os.path.join(DIST_APP, "使用说明.txt"))
# 清理运行时残留
for sub in ("web_start_out.log", "web_start_err.log", "desktop_trace.log"):
    p = os.path.join(DIST_APP, "PhantomCore", sub)
    if os.path.exists(p):
        os.remove(p)

# 2. 便携版目录
if os.path.exists(PORTABLE):
    shutil.rmtree(PORTABLE)
shutil.copytree(DIST_APP, PORTABLE)

# 3. zip(带重试, 应对杀软锁文件)
if os.path.exists(ZIP):
    os.remove(ZIP)
total, locked = 0, []
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(DIST_APP):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, DIST_APP)
            written = False
            for _ in range(6):
                try:
                    z.write(fp, rel)
                    written = True
                    break
                except PermissionError:
                    time.sleep(3)
            if written:
                total += 1
            else:
                locked.append(rel)
with zipfile.ZipFile(ZIP, "r") as z:
    names = z.namelist()
ok = any(n.endswith("PhantomCore/PhantomCore.exe") for n in names)
size_gb = os.path.getsize(ZIP) / 1024 ** 3
print("files_written:", total, "locked:", locked)
print("entries:", len(names), "has_engine_exe:", ok, "zip_gb: %.2f" % size_gb)
print("RESULT:", "ZIP_OK" if ok and not locked else "ZIP_BAD")
