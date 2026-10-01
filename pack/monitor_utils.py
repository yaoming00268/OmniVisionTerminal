# pack/monitor_utils.py — 多显示器定位工具(调试窗口放副屏)
import ctypes
from ctypes import wintypes

MONITORINFOF_PRIMARY = 1


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def secondary_monitor_rect():
    """返回第一个非主显示器的 (x, y, w, h); 无副屏时返回主屏。"""
    monitors = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(RECT), ctypes.c_double)

    def cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(
                ctypes.c_void_p(hMonitor), ctypes.byref(info)):
            r = info.rcMonitor
            monitors.append((bool(info.dwFlags & MONITORINFOF_PRIMARY),
                             (r.left, r.top, r.right - r.left, r.bottom - r.top)))
        return True

    proc = MonitorEnumProc(cb)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc, 0)
    if not monitors:
        return (0, 0, 1280, 800)
    for primary, rect in monitors:
        if not primary:
            return rect
    return monitors[0][1]


def center_on(rect, w, h):
    """计算在 rect (x,y,w,h) 内居中放置 w×h 窗口的 (x, y)。"""
    x = rect[0] + max(0, (rect[2] - w) // 2)
    y = rect[1] + max(0, (rect[3] - h) // 2)
    return x, y


def window_pos(w, h):
    """获取副屏居中的 (x, y); 优先副屏, 无则主屏。"""
    return center_on(secondary_monitor_rect(), w, h)
