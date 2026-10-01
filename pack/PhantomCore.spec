# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['G:\\chaofen5\\pack\\obf_dist\\main.py'],
    pathex=['G:\\chaofen5\\pack\\obf_dist'],
    binaries=[],
    datas=[('G:\\chaofen5\\web', 'web'), ('G:\\chaofen5\\pack\\obf_dist\\core', 'core'), ('G:\\chaofen5\\pack\\obf_dist\\app', 'app'), ('G:\\chaofen5\\pack\\obf_dist\\desktop_api.py', '.'), ('G:\\chaofen5\\monitor_utils.py', '.')],
    hiddenimports=['pyarmor_runtime_000000', 'cv2', 'torch', 'numpy', 'psutil', 'requests', 'PIL', 'spandrel', 'imageio_ffmpeg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorrt', 'matplotlib', 'scipy', 'pandas', 'IPython', 'jupyter', 'tkinter', 'PyQt5', 'PyQt6', 'gradio', 'moviepy', 'basicsr', 'realesrgan'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhantomCore',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhantomCore',
)
