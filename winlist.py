"""The windows on screen, for window snips (0.12.0).

`visible_windows()` returns the top-level windows a person can see, topmost
first, as rectangles in Qt's logical coordinates (the ones the selection
overlay works in). ShadowSnip's own windows are left out, so the overlay
never offers itself.

## Windows

`EnumWindows` lists top-level windows in z-order, topmost first. A window is
kept when it is visible, not minimised, not cloaked (DWM hides some windows
that are technically visible: other virtual desktops, suspended UWP apps),
and not the desktop itself. Its rectangle comes from
`DWMWA_EXTENDED_FRAME_BOUNDS`, the frame as drawn, without the invisible
resize border and shadow Windows 10 and 11 add around `GetWindowRect`.

Those rectangles are in physical pixels (ShadowSnip is per-monitor DPI
aware), while the overlay works in Qt's logical pixels, which differ per
monitor at different scales. Each rectangle is converted with the monitor it
mostly sits on: the monitor's native rectangle from `GetMonitorInfo`, its
logical one from the Qt screen with the same device name.

## Linux (X11)

`_NET_CLIENT_LIST_STACKING` on the root window lists managed windows bottom
to top. Each is asked for its position (`xwininfo`) and, through `xprop`, its
frame (`_NET_FRAME_EXTENTS`, so the title bar is included), its state (a
minimised window is `_NET_WM_STATE_HIDDEN`) and its process. Both tools come
with x11-utils, which install.sh already asks for.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect

# Windows smaller than this (logical pixels, either side) are not offered:
# invisible helper windows, one-pixel shims.
MIN_SIDE = 24
# At most this many windows are looked at on Linux, where each costs two
# small programs; more than enough to reach what is on top.
LINUX_MAX_WINDOWS = 60
LINUX_TIMEOUT = 2.0


@dataclass
class Window:
    """One window on screen (0.13.0): where it is, and how to reach it.

    `rect` is in Qt's logical coordinates. `handle` is the native window
    (an HWND on Windows), when there is one to capture directly. `covered`
    says another window on the list lies over part of it.
    """
    rect: QRect
    handle: int | None = None
    covered: bool = False


def _rect_of(item) -> QRect:
    return item.rect if isinstance(item, Window) else item


def visible_windows() -> list[Window]:
    """The windows on screen now, topmost first, in logical coordinates."""
    try:
        if sys.platform == "win32":
            found = _windows_win32()
        elif sys.platform.startswith("linux"):
            found = _windows_x11()
        else:
            found = []
    except Exception:  # noqa: BLE001 - window snips are an extra; never break the snip
        return []
    windows = [w if isinstance(w, Window) else Window(w) for w in found]
    windows = [w for w in windows if w.rect.width() >= MIN_SIDE and w.rect.height() >= MIN_SIDE]
    mark_covered(windows)
    return windows


def mark_covered(windows: list[Window]) -> None:
    """Set `covered` on every window something higher up the list overlaps."""
    for index, window in enumerate(windows):
        window.covered = any(above.rect.intersects(window.rect) for above in windows[:index])


def supported() -> bool:
    if sys.platform == "win32":
        return True
    return (
        sys.platform.startswith("linux")
        and os.environ.get("XDG_SESSION_TYPE", "x11").lower() != "wayland"
        and shutil.which("xprop") is not None
        and shutil.which("xwininfo") is not None
    )


def window_at(windows: list, point: QPoint):
    """The topmost window under `point` (a Window, or a QRect from a plain list), or None."""
    for item in windows:
        if _rect_of(item).contains(point):
            return item
    return None


# -- physical pixels to Qt's logical ones ---------------------------------------------------------
def to_logical(native: QRect, monitors: list[tuple[QRect, QRect]]) -> QRect:
    """`native` (physical pixels) in Qt's logical pixels.

    `monitors` is (native rectangle, logical rectangle) per monitor. The
    monitor holding most of the window decides the scale, as it does for the
    window itself on Windows.
    """
    best, best_area = None, -1
    for native_rect, logical_rect in monitors:
        overlap = native_rect.intersected(native)
        area = overlap.width() * overlap.height() if not overlap.isEmpty() else 0
        if area > best_area:
            best, best_area = (native_rect, logical_rect), area
    if best is None or best_area <= 0:
        # Off every monitor: the nearest one's scale is as good as any.
        if not monitors:
            return QRect(native)
        best = min(monitors, key=lambda m: _distance(m[0], native))
    native_rect, logical_rect = best
    scale = native_rect.width() / logical_rect.width() if logical_rect.width() else 1.0
    if scale <= 0:
        scale = 1.0
    x = logical_rect.x() + (native.x() - native_rect.x()) / scale
    y = logical_rect.y() + (native.y() - native_rect.y()) / scale
    return QRect(round(x), round(y), round(native.width() / scale), round(native.height() / scale))


def _distance(a: QRect, b: QRect) -> float:
    dx = a.center().x() - b.center().x()
    dy = a.center().y() - b.center().y()
    return (dx * dx + dy * dy) ** 0.5


def _qt_monitors(native_of=None) -> list[tuple[QRect, QRect]]:
    """(native, logical) for each Qt screen. `native_of(screen)` overrides the native one."""
    from PySide6.QtGui import QGuiApplication

    out = []
    for screen in QGuiApplication.screens():
        logical = screen.geometry()
        native = native_of(screen) if native_of is not None else None
        if native is None:
            ratio = screen.devicePixelRatio() or 1.0
            native = QRect(round(logical.x() * ratio), round(logical.y() * ratio),
                           round(logical.width() * ratio), round(logical.height() * ratio))
        out.append((native, logical))
    return out


# -- Windows --------------------------------------------------------------------------------------
# Window classes that are the desktop, not a window on it.
_DESKTOP_CLASSES = {"Progman", "WorkerW"}


def _windows_win32() -> list[QRect]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    own_pid = os.getpid()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14

    found: list[tuple[int, QRect]] = []

    def keep(hwnd) -> None:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value in _DESKTOP_CLASSES:
            return
        cloaked = ctypes.c_int(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                        ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return
        rect = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
                                        ctypes.sizeof(rect)) != 0:
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return
        found.append((int(hwnd), QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)))

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def on_window(hwnd, _lparam):
        try:
            keep(hwnd)
        except Exception:  # noqa: BLE001 - one odd window must not end the list
            pass
        return True

    user32.EnumWindows(callback_type(on_window), 0)
    monitors = _qt_monitors(_win32_native_rect)
    return [Window(to_logical(r, monitors), handle) for handle, r in found]


def _win32_native_rect(screen) -> QRect | None:
    """The monitor's rectangle in physical pixels, matched by device name."""
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    found: list[QRect] = []
    wanted = screen.name()
    monitor_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def on_monitor(handle, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)) and info.szDevice == wanted:
            r = info.rcMonitor
            found.append(QRect(r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, monitor_proc(on_monitor), 0)
    return found[0] if found else None


# -- Linux (X11) ----------------------------------------------------------------------------------
def _run(*args: str) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=LINUX_TIMEOUT)
    return done.stdout if done.returncode == 0 else ""


def parse_client_list(text: str) -> list[str]:
    """Window ids from `xprop -root _NET_CLIENT_LIST_STACKING`, bottom to top."""
    return re.findall(r"0x[0-9a-fA-F]+", text.split("#", 1)[1]) if "#" in text else []


def parse_xwininfo(text: str) -> QRect | None:
    """The window's area from `xwininfo -id`, or None when it is not viewable."""
    values = {}
    for key, pattern in (("x", r"Absolute upper-left X:\s+(-?\d+)"),
                         ("y", r"Absolute upper-left Y:\s+(-?\d+)"),
                         ("w", r"Width:\s+(\d+)"), ("h", r"Height:\s+(\d+)")):
        match = re.search(pattern, text)
        if not match:
            return None
        values[key] = int(match.group(1))
    if "IsViewable" not in text:
        return None
    return QRect(values["x"], values["y"], values["w"], values["h"])


def parse_xprop(text: str) -> tuple[tuple[int, int, int, int], bool, int | None]:
    """(frame extents left, right, top, bottom), whether minimised, and the pid."""
    extents = (0, 0, 0, 0)
    match = re.search(r"_NET_FRAME_EXTENTS\(CARDINAL\) = (\d+), (\d+), (\d+), (\d+)", text)
    if match:
        extents = tuple(int(v) for v in match.groups())
    hidden = "_NET_WM_STATE_HIDDEN" in text
    pid_match = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", text)
    return extents, hidden, int(pid_match.group(1)) if pid_match else None


def _windows_x11() -> list[QRect]:
    if not supported():
        return []
    ids = parse_client_list(_run("xprop", "-root", "_NET_CLIENT_LIST_STACKING"))
    own_pid = os.getpid()
    rects: list[QRect] = []
    for window in reversed(ids[-LINUX_MAX_WINDOWS:]):  # topmost first
        props = _run("xprop", "-id", window, "_NET_FRAME_EXTENTS", "_NET_WM_STATE", "_NET_WM_PID")
        (left, right, top, bottom), hidden, pid = parse_xprop(props)
        if hidden or pid == own_pid:
            continue
        area = parse_xwininfo(_run("xwininfo", "-id", window))
        if area is None:
            continue
        rects.append(area.adjusted(-left, -top, right, bottom))
    monitors = _qt_monitors()
    return [to_logical(r, monitors) for r in rects]


# -- a covered window, from the window itself (Windows, 0.13.0) --------------------------------
# PrintWindow's PW_RENDERFULLCONTENT: asks DWM for the window's own content,
# which is what makes GPU-drawn windows (browsers, Electron) come out at all.
PW_RENDERFULLCONTENT = 2
# A capture this close to all black is a window that would not draw itself
# for PrintWindow (some games and video players): use the screen instead.
BLACK_SHARE = 0.97


def capture_window(handle: int):
    """The window's own picture (a QImage, physical pixels), frame as drawn, or None.

    For a window another one covers: cut from the screen, the covering
    window would be in the snip. Windows only; None anywhere else, or when
    the window would not draw itself.
    """
    if sys.platform != "win32" or not handle:
        return None
    try:
        image = _print_window(handle)
    except Exception:  # noqa: BLE001 - the screen is the fallback
        return None
    if image is None or image.isNull() or mostly_black(image):
        return None
    return image


def mostly_black(image) -> bool:
    """Whether nearly every sampled pixel is pure black: a capture that failed."""
    from PySide6.QtGui import QColor

    w, h = image.width(), image.height()
    if w <= 0 or h <= 0:
        return True
    samples = black = 0
    for y in range(0, h, max(1, h // 24)):
        for x in range(0, w, max(1, w // 24)):
            samples += 1
            if QColor(image.pixel(x, y)).rgb() & 0xFFFFFF == 0:
                black += 1
    return samples == 0 or black / samples >= BLACK_SHARE


def _print_window(handle: int):
    import ctypes
    from ctypes import wintypes

    from PySide6.QtGui import QImage

    user32, gdi32, dwmapi = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.dwmapi
    hwnd = wintypes.HWND(handle)
    outer = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(outer)):
        return None
    width, height = outer.right - outer.left, outer.bottom - outer.top
    if width <= 0 or height <= 0:
        return None
    frame = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame)) != 0:
        frame = outer

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    try:
        old = gdi32.SelectObject(memory_dc, bitmap)
        drawn = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        gdi32.SelectObject(memory_dc, old)
        if not drawn:
            return None
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = width, -height  # negative: top row first
        header.biPlanes, header.biBitCount, header.biCompression = 1, 32, 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            return None
        image = QImage(buffer.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
    # Trim the invisible resize border and shadow: keep the frame as drawn.
    crop = QRect(frame.left - outer.left, frame.top - outer.top,
                 frame.right - frame.left, frame.bottom - frame.top).intersected(image.rect())
    return image.copy(crop) if not crop.isEmpty() else image
