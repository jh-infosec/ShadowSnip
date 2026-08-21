"""Copy on select.

When this is engaged, finishing a left-button drag copies whatever was
highlighted, so a selection reaches the clipboard without Ctrl+C. Linux has
had this for decades as the PRIMARY selection; Windows has no equivalent, and
no API that reports "the user just highlighted something" either.

So the mechanism is: watch for a left-button drag ending, synthesise Ctrl+C
into the focused window, and see whether the clipboard sequence number moved.
If it did, something was selected. If it did not, nothing was, and nothing
has been disturbed.

A double-click selects a word and a triple-click selects a line, in every text
control worth the name, so those count as selections too. They arrive by a
different route: a low-level mouse hook never receives WM_LBUTTONDBLCLK,
because that message is synthesised further up the stack when an event is
dispatched to a window with CS_DBLCLKS, and so exists only inside the target
application. To know a double-click happened we apply the same rule Windows
does -- two presses inside GetDoubleClickTime() and inside the double-click
rectangle -- and count them ourselves. That is what `_ClickRun` is.

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
  - Password managers are skipped by executable name. This one is not about
    misfiring: the copy would work perfectly. Double-clicking an entry in
    KeePass copies the password, and a feature that reads the clipboard back
    automatically has no business being anywhere near that.
  - ShadowSnip's own windows are skipped, so dragging the selection overlay
    does not trigger a copy.
  - Nothing fires while a modifier is held, since Ctrl+Shift+C and Ctrl+Alt+C
    mean other things in browsers and IDEs.
  - Nothing fires for a single click that is not part of a click run, and a
    drag shorter than a few pixels is a click.

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
    _kernel32 = ctypes.windll.kernel32
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
    _user32.GetDoubleClickTime.restype = wintypes.UINT
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    # Without an explicit restype a HANDLE comes back as a signed int and is
    # truncated on 64-bit, which turns a valid handle into a bogus one.
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
else:
    _user32 = None
    _kernel32 = None

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002

# A word is selected while the application handles the second button *down*,
# so by the time the matching button up reaches the hook the selection is
# almost always already made. Almost: a busy message queue can still be a few
# milliseconds behind, and a Ctrl+C that lands first copies nothing.
DOUBLE_CLICK_SETTLE_MS = 60

# How long to wait for the target application to answer the keystroke before
# reading the clipboard sequence number back.
READ_BACK_MS = 120

# Fire on a double-click (word) and a triple-click (line), and stop there.
# Past three, someone is drumming on the mouse, not selecting text.
MAX_CLICKS = 3

CLICK_KINDS = {2: "word", 3: "line"}

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

# Applications whose clipboard is none of our business. Unlike the class list
# above, the danger here is not that the copy misfires -- it is that it works.
# Always applied, and not switchable from Settings: the cost of being unable to
# copy-on-select inside a password manager is that you press Ctrl+C like anyone
# else, and the cost of the other mistake is a password in a log file.
BLOCKED_PROCESSES = {
    "keepass.exe",
    "keepassxc.exe",
    "keepassxc-proxy.exe",
    "1password.exe",
    "1passwordbrowsersupport.exe",
    "bitwarden.exe",
    "bitwarden-desktop.exe",
    "dashlane.exe",
    "enpass.exe",
    "nordpass.exe",
    "keeperpasswordmanager.exe",
    "protonpass.exe",
    "roboform.exe",
    "lastpass.exe",
    "credentialuibroker.exe",  # the Windows credential prompt
}


class AutoCopyError(RuntimeError):
    pass


class _ClickRun:
    """Counts consecutive clicks the way Windows counts them.

    Pure state, no Win32 and no Qt, because the interesting part is the rule
    rather than the plumbing: a press continues the run when it lands inside
    the double-click interval *and* inside the double-click rectangle of the
    press before it. Anything else starts a new run.
    """

    def __init__(self, interval_ms: int = 500, slop: tuple[int, int] = (2, 2)):
        self.interval_ms = interval_ms
        self.slop = slop
        self._count = 0
        self._at: tuple[int, int, int] | None = None  # time, x, y

    @property
    def count(self) -> int:
        return self._count

    def press(self, time_ms: int, x: int, y: int) -> int:
        """Record a press and return its position in the run: 1, 2, 3, ..."""
        self._count = self._count + 1 if self._continues(time_ms, x, y) else 1
        self._at = (time_ms, x, y)
        return self._count

    def reset(self) -> None:
        self._count = 0
        self._at = None

    def _continues(self, time_ms: int, x: int, y: int) -> bool:
        if self._at is None:
            return False
        last_time, last_x, last_y = self._at
        gap = time_ms - last_time
        # The hook's timestamp is a 32-bit tick count, so it wraps roughly
        # every 49 days. A negative gap means it wrapped between two presses;
        # treating that as a new run costs one missed double-click a month and
        # a half, which is cheaper than the arithmetic to handle it properly.
        if gap < 0 or gap > self.interval_ms:
            return False
        return abs(x - last_x) <= self.slop[0] and abs(y - last_y) <= self.slop[1]


class AutoCopy(QObject):
    """Engages the hook and reports text that reached the clipboard."""

    # (text, kind) where kind is "selection", "word" or "line".
    copied = Signal(str, str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._hook = None
        self._proc = None  # kept alive; a collected callback crashes the hook
        self._paused = False
        self._down: tuple[int, int] | None = None
        self._clicks = 0
        self._run = _ClickRun()
        self._last_text: str | None = None

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

        # Read the mouse settings now rather than at import time, so changing
        # the double-click speed in Control Panel takes effect on the next
        # toggle instead of the next restart.
        interval, slop = _double_click_metrics()
        self._run = _ClickRun(interval, slop)

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
        self._clicks = 0
        self._run.reset()
        self._last_text = None

    def pause(self) -> None:
        """Stop reacting without tearing the hook down, during a snip."""
        self._paused = True
        self._down = None
        self._clicks = 0
        self._run.reset()

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
                    x, y, when = _event(lparam)
                    self._down = (x, y)
                    self._clicks = self._run.press(when, x, y)
                elif wparam == WM_LBUTTONUP:
                    start, self._down = self._down, None
                    if start is not None:
                        x, y, _ = _event(lparam)
                        self._on_release(start, (x, y))
        except Exception:  # noqa: BLE001 - never let a raise reach the chain
            self._down = None
            self._clicks = 0
        return _user32.CallNextHookEx(self._hook or 0, code, wparam, lparam)

    def _on_release(self, start, end) -> None:
        """Decide what a finished button press was, and schedule the copy.

        Out of the hook and into the event loop before doing anything that
        could take a while.
        """
        if self._is_drag(start, end):
            # A drag is not a click, and the run it interrupted is over.
            self._run.reset()
            self._clicks = 0
            QTimer.singleShot(0, lambda: self._capture("selection"))
            return

        clicks = self._clicks
        if clicks < 2 or clicks > MAX_CLICKS:
            return
        if not self._cfg.get("auto_copy_double_click", True):
            return
        kind = CLICK_KINDS.get(clicks, "selection")
        QTimer.singleShot(
            DOUBLE_CLICK_SETTLE_MS, lambda: self._capture(kind)
        )

    def _is_drag(self, start, end) -> bool:
        minimum = int(self._cfg.get("auto_copy_min_drag", 8) or 0)
        return abs(end[0] - start[0]) >= minimum or abs(end[1] - start[1]) >= minimum

    # -- the copy ----------------------------------------------------------
    def _capture(self, kind: str = "selection") -> None:
        if self._paused or not self.engaged:
            return
        if _modifier_held():
            return

        window = _user32.GetForegroundWindow()
        if not window or _is_own_window(window):
            return
        if self._cfg.get("auto_copy_skip_consoles", True):
            if _class_name(window) in BLOCKED_CLASSES:
                return
        if _process_name(window) in self._blocked_processes():
            # Deliberately before the keystroke, not after: the point is that
            # nothing is ever synthesised into a password manager at all.
            return

        before = _clipboard_sequence()
        _send_ctrl_c()
        # Give the target application a moment to answer the keystroke.
        QTimer.singleShot(READ_BACK_MS, lambda: self._read_back(before, kind))

    def _blocked_processes(self) -> set[str]:
        extra = self._cfg.get("auto_copy_extra_blocked") or ()
        # config normalises this to a list, but a string here would iterate one
        # character at a time and quietly block nothing, which is the failure
        # mode this whole list exists to avoid.
        if isinstance(extra, str):
            extra = extra.replace(",", " ").split()
        return BLOCKED_PROCESSES | {str(name).strip().lower() for name in extra if name}

    def _read_back(self, before: int, kind: str) -> None:
        if _clipboard_sequence() == before:
            # Nothing was selected, so nothing was copied and nothing was lost.
            return
        text = _clipboard_text()
        if not text:
            return
        if self._cfg.get("auto_copy_dedupe", True) and text == self._last_text:
            # Re-selecting the same word is the commonest gesture there is, and
            # announcing it every time turns a useful confirmation into noise.
            return
        self._last_text = text
        self.copied.emit(text, kind)


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


def _event(lparam) -> tuple[int, int, int]:
    """The x, y and timestamp of one mouse event."""
    data = ctypes.cast(
        ctypes.c_void_p(lparam), ctypes.POINTER(_MSLLHOOKSTRUCT)
    ).contents
    return data.pt.x, data.pt.y, int(data.time)


def _double_click_metrics() -> tuple[int, tuple[int, int]]:
    """The user's double-click interval, and the slop allowed around it.

    SM_CXDOUBLECLK is the *width* of the rectangle the second click has to
    land in, so what a press may deviate from the one before it is half that.
    """
    if _user32 is None:
        return 500, (2, 2)
    try:
        interval = int(_user32.GetDoubleClickTime()) or 500
        width = int(_user32.GetSystemMetrics(SM_CXDOUBLECLK)) or 4
        height = int(_user32.GetSystemMetrics(SM_CYDOUBLECLK)) or 4
    except OSError:
        return 500, (2, 2)
    return interval, (max(1, width // 2), max(1, height // 2))


def _modifier_held() -> bool:
    get = _user32.GetAsyncKeyState
    return any(
        get(key) & 0x8000
        for key in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)
    )


def _class_name(window) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(window, buffer, 256)
    return buffer.value


def _window_pid(window) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return pid.value


def _is_own_window(window) -> bool:
    return _window_pid(window) == os.getpid()


def _process_name(window) -> str:
    """The lowercase executable name behind a window, or "" if unknowable.

    PROCESS_QUERY_LIMITED_INFORMATION rather than PROCESS_QUERY_INFORMATION:
    it is the one right that works across integrity levels, so an elevated
    window still answers instead of failing open. Failing open is the bad
    direction here -- an unreadable name must not become a name that is not
    on the block list.
    """
    if _kernel32 is None:
        return ""
    pid = _window_pid(window)
    if not pid:
        return ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return os.path.basename(buffer.value).lower()
    except OSError:
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _send_ctrl_c() -> None:
    keybd_event = _user32.keybd_event
    keybd_event(VK_CONTROL, 0, 0, 0)
    keybd_event(VK_C, 0, 0, 0)
    keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _clipboard_sequence() -> int:
    """Changes whenever anything writes to the clipboard, without opening it."""
    try:
        return int(_user32.GetClipboardSequenceNumber())
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
