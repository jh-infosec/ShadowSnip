"""Copy on select.

When this is engaged, finishing a left-button drag copies whatever was
highlighted, so a selection reaches the clipboard without Ctrl+C. Linux has
had this for decades as the PRIMARY selection; Windows has no equivalent, and
no API that reports "the user just highlighted something" either.

So the mechanism is: watch for a left-button drag ending, synthesise Ctrl+C
into the focused window, and see whether the clipboard sequence number moved.
If it did, something was selected. If it did not, nothing was, and nothing
has been disturbed.

The hook is WH_MOUSE_LL, which sees mouse events across the whole desktop.
`architecture.md` argues against a keyboard hook for ShadowSnip's hotkey, and
that reasoning still holds: a keyboard hook would see every keystroke typed
anywhere. A mouse hook sees coordinates and button states, which is a much
smaller thing to be trusted with, and it is the only way this feature works at
all. It stays off by default and is engaged deliberately.

Synthesising Ctrl+C into an arbitrary window is the part that can actually do
damage, so it is fenced in:

  - Console windows are skipped. In a terminal with nothing selected, Ctrl+C
    is a break, and cancelling a running scan because of a stray drag would
    be an unpleasant surprise. Windows Terminal has `copyOnSelect` built in,
    which is the better answer there anyway.
  - Explorer and the desktop are skipped. A rubber-band drag there selects
    files, and Ctrl+C would quietly put those files on the clipboard.
  - ShadowSnip's own windows are skipped, so dragging the selection overlay
    does not trigger a copy.
  - Nothing fires while a modifier is held, since Ctrl+Shift+C and Ctrl+Alt+C
    mean other things in browsers and IDEs.
  - Nothing fires for a drag shorter than a few pixels, which is a click.

The hook callback itself does nothing but record state. Windows silently
unhooks a low-level hook whose callback overruns `LowLevelHooksTimeout`, so
the actual work is handed to the Qt event loop and happens after the callback
has returned.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD
    ]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    ]
    _user32.CallNextHookEx.restype = ctypes.c_ssize_t
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.GetForegroundWindow.restype = wintypes.HWND
else:
    _user32 = None

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002

# Windows where a synthetic Ctrl+C would mean something other than "copy".
BLOCKED_CLASSES = {
    "ConsoleWindowClass",  # cmd.exe, the legacy console host
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "PseudoConsoleWindow",
    "CabinetWClass",  # Explorer
    "ExploreWClass",
    "Progman",  # the desktop
    "WorkerW",
}


class AutoCopyError(RuntimeError):
    pass


class AutoCopy(QObject):
    """Engages the hook and reports text that reached the clipboard."""

    copied = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._hook = None
        self._proc = None  # kept alive; a collected callback crashes the hook
        self._paused = False
        self._down: tuple[int, int] | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def engaged(self) -> bool:
        return self._hook is not None

    def configure(self, cfg: dict) -> None:
        """Point at the current config dict after a settings save."""
        self._cfg = cfg

    def engage(self) -> None:
        if self._hook is not None:
            return
        if not self.supported:
            raise AutoCopyError("copy on select is only wired up on Windows")

        proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        self._proc = proc_type(self._on_mouse_event)
        hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not hook:
            self._proc = None
            # GetLastError, not ctypes.get_last_error: the latter reads the copy
            # ctypes saves only for libraries built with use_last_error=True,
            # which ctypes.windll is not, so it would always report 0.
            raise AutoCopyError(
                f"the mouse hook was refused (error {ctypes.GetLastError()})"
            )
        self._hook = hook

    def release(self) -> None:
        if self._hook is not None and self.supported:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except OSError:
                pass
        self._hook = None
        self._proc = None
        self._down = None

    def pause(self) -> None:
        """Stop reacting without tearing the hook down, during a snip."""
        self._paused = True
        self._down = None

    def resume(self) -> None:
        self._paused = False

    # -- the hook ----------------------------------------------------------
    def _on_mouse_event(self, code, wparam, lparam):
        """Runs on every mouse event. Records state and returns immediately.

        Anything that raises here is swallowed: an exception escaping a
        low-level hook makes Windows throttle then silently drop it, so a bug
        in our own logic must never reach the CallNextHookEx at the end.
        """
        try:
            if code >= 0 and not self._paused:
                if wparam == WM_LBUTTONDOWN:
                    self._down = _point(lparam)
                elif wparam == WM_LBUTTONUP:
                    start, self._down = self._down, None
                    if start is not None and self._is_drag(start, _point(lparam)):
                        # Out of the hook and into the event loop before doing
                        # anything that could take a while.
                        QTimer.singleShot(0, self._capture)
        except Exception:  # noqa: BLE001 - never let a raise reach the chain
            self._down = None
        return _user32.CallNextHookEx(self._hook or 0, code, wparam, lparam)

    def _is_drag(self, start, end) -> bool:
        minimum = int(self._cfg.get("auto_copy_min_drag", 8) or 0)
        return abs(end[0] - start[0]) >= minimum or abs(end[1] - start[1]) >= minimum

    # -- the copy ----------------------------------------------------------
    def _capture(self) -> None:
        if self._paused or not self.engaged:
            return
        if _modifier_held():
            return

        window = ctypes.windll.user32.GetForegroundWindow()
        if not window or _is_own_window(window):
            return
        if self._cfg.get("auto_copy_skip_consoles", True):
            if _class_name(window) in BLOCKED_CLASSES:
                return

        before = _clipboard_sequence()
        _send_ctrl_c()
        # Give the target application a moment to answer the keystroke.
        QTimer.singleShot(120, lambda: self._read_back(before))

    def _read_back(self, before: int) -> None:
        if _clipboard_sequence() == before:
            # Nothing was selected, so nothing was copied and nothing was lost.
            return
        text = _clipboard_text()
        if text:
            self.copied.emit(text)


# -- Win32 helpers ---------------------------------------------------------
class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", _POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def _point(lparam) -> tuple[int, int]:
    data = ctypes.cast(
        ctypes.c_void_p(lparam), ctypes.POINTER(_MSLLHOOKSTRUCT)
    ).contents
    return data.pt.x, data.pt.y


def _modifier_held() -> bool:
    get = ctypes.windll.user32.GetAsyncKeyState
    return any(
        get(key) & 0x8000
        for key in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)
    )


def _class_name(window) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(window, buffer, 256)
    return buffer.value


def _is_own_window(window) -> bool:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return pid.value == os.getpid()


def _send_ctrl_c() -> None:
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event(VK_CONTROL, 0, 0, 0)
    keybd_event(VK_C, 0, 0, 0)
    keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _clipboard_sequence() -> int:
    """Changes whenever anything writes to the clipboard, without opening it."""
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except OSError:
        return 0


def _clipboard_text() -> str:
    try:
        import win32clipboard as clip
        import win32con
    except ImportError:
        from PySide6.QtWidgets import QApplication

        return QApplication.clipboard().text()

    try:
        clip.OpenClipboard()
    except Exception:  # noqa: BLE001 - pywin32 raises pywintypes.error
        return ""
    try:
        if not clip.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return ""
        return str(clip.GetClipboardData(win32con.CF_UNICODETEXT) or "")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            clip.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass
