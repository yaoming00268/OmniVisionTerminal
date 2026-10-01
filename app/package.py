import os
import zipfile

PACKAGE_DIR_NAME = "全能视像解析终端_WebApp"

def build_webapp_package(output_dir=None):
    """生成自包含 WebApp 引导包(zip): main.py + core/ + app/ + web/ + models/ + start_webui.bat。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not output_dir:
        output_dir = root
    os.makedirs(output_dir, exist_ok=True)
    zip_path = os.path.join(output_dir, f"{PACKAGE_DIR_NAME}.zip")
    entries = ["main.py", "start_webui.bat", "core", "app", "web", "models"]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            full = os.path.join(root, entry)
            if os.path.isfile(full):
                zf.write(full, os.path.join(PACKAGE_DIR_NAME, entry))
            elif os.path.isdir(full):
                for dirpath, dirnames, filenames in os.walk(full):
                    dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv", "webapp_uploads")]
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        rel = os.path.relpath(fp, root)
                        zf.write(fp, os.path.join(PACKAGE_DIR_NAME, rel))
    return zip_path
