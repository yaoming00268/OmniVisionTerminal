# monitor_utils.py — 多显示器定位工具(调试窗口避开用户主屏)
# 用户主屏为型号以 'P' 开头的显示器(P245MS 等)。
# 调试目标屏选择顺序:
#   1) 型号不以 P 开头的显示器(用户不用的屏)
#   2) 非 Windows 主屏的显示器
#   3) 仅一台时返回该屏
import ctypes
import os
from ctypes import wintypes

MONITORINFOF_PRIMARY = 1
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128)]


def _all_monitors():
    """返回 [(primary, (x,y,w,h), device_string)]，按系统枚举顺序。"""
    rects = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(RECT), ctypes.c_double)

    def cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(
                ctypes.c_void_p(hMonitor), ctypes.byref(info)):
            r = info.rcMonitor
            rects.append((bool(info.dwFlags & MONITORINFOF_PRIMARY),
                          (r.left, r.top, r.right - r.left, r.bottom - r.top)))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)

    devs = []
    i = 0
    while True:
        d = DISPLAY_DEVICE()
        d.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        if d.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            devs.append(d.DeviceString.strip())
        i += 1

    out = []
    for idx, (primary, rect) in enumerate(rects):
        ds = devs[idx] if idx < len(devs) else ""
        out.append((primary, rect, ds))
    return out


def physical_monitor_rects():
    """返回各显示器物理像素坐标 (x, y, w, h), 非 Windows 主屏优先。
    SetProcessDPIAware 后 EnumDisplayMonitors 返回物理像素(与 PIL ImageGrab 一致)。"""
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    MONITORINFOF_PRIMARY = 1

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint32),
            ("rcMonitor", ctypes.c_long * 4),
            ("rcWork", ctypes.c_long * 4),
            ("dwFlags", ctypes.c_uint32),
        ]

    monitors = []

    def _cb(hmon, hdc, lprc, dw):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rc = mi.rcMonitor
        monitors.append(
            (bool(mi.dwFlags & MONITORINFOF_PRIMARY),
             (rc[0], rc[1], rc[2] - rc[0], rc[3] - rc[1])))
        return True

    EnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_long * 4), ctypes.c_void_p)
    ctypes.windll.user32.EnumDisplayMonitors(0, 0, EnumProc(_cb), 0)
    if not monitors:
        return [(True, (0, 0, 1280, 800))]
    return monitors


def debug_monitor_rect():
    """调试窗口目标屏矩形 (x, y, w, h)。
    用户主屏 = Windows 主显示器(如 P245MS 2560x1440),
    调试窗口固定显示在 Windows 非主屏(副屏), 避免打扰用户。"""
    ms = _all_monitors()
    if not ms:
        return (0, 0, 1280, 800)
    # 非 Windows 主屏优先(用户主屏为 Windows 主屏)
    for primary, rect, ds in ms:
        if not primary:
            return rect
    # 仅一台时返回该屏
    return ms[0][1]


def debug_physical_rect():
    """调试屏物理像素矩形(供 ImageGrab 截图用)。"""
    for primary, rect in physical_monitor_rects():
        if not primary:
            return rect
    return physical_monitor_rects()[0][1]


def center_on(rect, w, h):
    """计算在 rect (x,y,w,h) 内居中放置 w×h 窗口的 (x, y)。"""
    x = rect[0] + max(0, (rect[2] - w) // 2)
    y = rect[1] + max(0, (rect[3] - h) // 2)
    return x, y


def window_pos(w, h, secondary=True):
    """返回窗口定位 (x, y)。默认调试屏(避开用户主屏);
    环境变量 VT_SECONDARY=0 时使用 Windows 主屏。"""
    if os.environ.get("VT_SECONDARY") == "0":
        rect = None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        hmon = ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(0, 0), 2)
        if hmon and ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            rect = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        if rect is None:
            rect = debug_monitor_rect()
    else:
        rect = debug_monitor_rect()
    return center_on(rect, w, h)
