"""Locking an encrypted lab by itself (0.18.0): after idle time, and when the computer locks or sleeps.

A locked lab keeps running: it is still the lab snips are filed into, but its
key is forgotten (vault.lock), its list and preview are hidden, and the next
thing that needs it (a snip, a note, the list) asks for the password first.

## Idle

"Idle" means nobody has touched the computer, not just ShadowSnip:

- Windows: `GetLastInputInfo`, the time since the last key or mouse input
  anywhere in the session.
- Linux on X11: the XScreenSaver extension (`libXss`), the same measure the
  screensaver uses.
- Elsewhere (Wayland, no libXss): the time since ShadowSnip itself was last
  used, which is shorter-lived but errs towards locking.

The check runs every `CHECK_MS`. A clip being recorded holds the lock off:
recording is use even when nobody types.

## Locking with the computer

- Windows: the session's lock (Win+L, the lid, the screensaver's lock) and
  suspend, from `WM_WTSSESSION_CHANGE` and `WM_POWERBROADCAST`, through a Qt
  native event filter.
- Linux: logind's `Lock` signal for this session and `PrepareForSleep`, over
  D-Bus. Desktops that lock without telling logind are covered by the idle
  timer instead.
"""

from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal, Slot

CHECK_MS = 20_000
MINUTES_RANGE = (0, 240)
DEFAULT_MINUTES = 15

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x4
NOTIFY_FOR_THIS_SESSION = 0


# -- how long the computer has been idle ------------------------------------------------------
def _windows_idle() -> float | None:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except (AttributeError, OSError):
        return None


_xss = None


def _x11_idle() -> float | None:
    """Milliseconds since the last input, from XScreenSaverQueryInfo; None without X or libXss."""
    global _xss
    import os

    if not os.environ.get("DISPLAY") or os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
        return None
    try:
        if _xss is None:
            import ctypes.util

            x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss") or "libXss.so.1")

            class Info(ctypes.Structure):
                _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                            ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong),
                            ("eventMask", ctypes.c_ulong)]

            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(Info)
            xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Info)]
            display = x11.XOpenDisplay(None)
            if not display:
                _xss = False
                return None
            _xss = (xss, display, x11.XDefaultRootWindow(display), xss.XScreenSaverAllocInfo())
        if _xss is False:
            return None
        xss, display, root, info = _xss
        if not xss.XScreenSaverQueryInfo(display, root, info):
            return None
        return info.contents.idle / 1000.0
    except (OSError, AttributeError):
        _xss = False
        return None


def system_idle() -> float | None:
    """Seconds since the last input anywhere on the computer, or None when it cannot be told."""
    if sys.platform == "win32":
        return _windows_idle()
    return _x11_idle()


class AutoLock(QObject):
    """Says when the lab should lock for idleness. `due` carries a reason for the status line."""

    due = Signal(str)

    def __init__(self, minutes=lambda: DEFAULT_MINUTES, active=lambda: True, busy=lambda: False,
                 idle=system_idle, parent=None):
        """`minutes()` the limit (0 = never), `active()` whether there is an unlocked
        encrypted lab to lock, `busy()` whether something (a recording) holds it off."""
        super().__init__(parent)
        self._minutes = minutes
        self._active = active
        self._busy = busy
        self._idle = idle
        self._last_use = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_MS)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def touch(self) -> None:
        """ShadowSnip was used: the fallback idle clock starts again."""
        self._last_use = time.monotonic()

    def idle_seconds(self) -> float:
        measured = self._idle()
        own = time.monotonic() - self._last_use
        return own if measured is None else min(measured, own)

    def check(self) -> bool:
        minutes = int(self._minutes() or 0)
        if minutes <= 0 or not self._active():
            return False
        if self._busy():
            self.touch()
            return False
        if self.idle_seconds() >= minutes * 60:
            self.due.emit(f"after {minutes} minute{'s' if minutes != 1 else ''} idle")
            return True
        return False


# -- when the computer locks or sleeps ------------------------------------------------------------
class _WindowsFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", "windows_generic_MSG"):
            return False, 0
        try:
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError, OSError):
            return False, 0
        if msg.message == WM_WTSSESSION_CHANGE and msg.wParam == WTS_SESSION_LOCK:
            self._callback("when Windows locked")
        elif msg.message == WM_POWERBROADCAST and msg.wParam == PBT_APMSUSPEND:
            self._callback("as the computer went to sleep")
        return False, 0


class SessionWatcher(QObject):
    """Emits `locking(reason)` when the computer locks or is about to sleep."""

    locking = Signal(str)

    def __init__(self, app, window=None, parent=None):
        super().__init__(parent)
        self._filter = None
        self.watching = False
        if sys.platform == "win32":
            self._watch_windows(app, window)
        else:
            self._watch_logind()

    def _watch_windows(self, app, window) -> None:
        try:
            self._filter = _WindowsFilter(self.locking.emit)
            app.installNativeEventFilter(self._filter)
            if window is not None:
                hwnd = int(window.winId())
                ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
            self.watching = True
        except (AttributeError, OSError):
            self.watching = False

    def _watch_logind(self) -> None:
        try:
            from PySide6.QtDBus import QDBusConnection
        except ImportError:
            return
        bus = QDBusConnection.systemBus()
        if not bus.isConnected():
            return
        ok_lock = bus.connect("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                              "org.freedesktop.login1.Session", "Lock", self, "_on_lock()")
        ok_sleep = bus.connect("org.freedesktop.login1", "/org/freedesktop/login1",
                               "org.freedesktop.login1.Manager", "PrepareForSleep", self, "_on_sleep(bool)")
        self.watching = bool(ok_lock or ok_sleep)

    @Slot()
    def _on_lock(self) -> None:
        self.locking.emit("when the session locked")

    @Slot(bool)
    def _on_sleep(self, starting: bool) -> None:
        if starting:
            self.locking.emit("as the computer went to sleep")
