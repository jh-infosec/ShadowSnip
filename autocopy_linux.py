"""Copy on select on Linux: the X11 primary selection, copied to the clipboard.

On Windows, copy on select needs a system-wide mouse hook and a synthetic
Ctrl+C (autocopy.py), with a long list of guards because a stray Ctrl+C in a
terminal interrupts whatever is running. X11 already does the hard half:
highlighting text anywhere puts it in the *primary selection*, the buffer
middle-click pastes from. All this has to do is notice the primary selection
change and copy it to the clipboard, so Ctrl+V pastes it too.

So there is no hook, no keystroke and no SIGINT risk. Double- and
triple-click work for free, because the application selecting the word or
line updates the primary selection itself.

What is kept from Windows: the password-manager block list (by process name,
with or without `.exe`), the **Never copy from** list, the dedupe, the pause
during a snip, and the `copied(text, kind)` signal the toast listens to.

It fails closed, as the Windows version does. The block list depends on
knowing which program the selection came from, which is read with `xprop`.
Without `xprop` copy on select will not start, and when the program in front
cannot be identified for one selection, that selection is not copied.

The selection changes continuously while a drag is in progress, so a copy is
made only once it has been still for a moment.

Wayland: the primary selection exists under most compositors, but a
background application is often not told when it changes. When the platform
has no selection at all, engaging says so rather than pretending to work.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard, QGuiApplication

from autocopy import BLOCKED_PROCESSES, AutoCopyError

# How long the selection must stay unchanged before it is copied. A drag
# updates it on every mouse move; copying each step would flood the clipboard
# and the toast.
SETTLE_MS = 300

# How long to wait for xprop when asking which program is in front.
_PROCESS_TIMEOUT = 1.5

# Linux names for the password managers blocked on Windows, plus the ones that
# only exist here. Compared by bare name, so `keepassxc` and `keepassxc.exe`
# are the same entry.
LINUX_BLOCKED = {
    "keepassxc",
    "keepassx",
    "keepass2",
    "1password",
    "bitwarden",
    "enpass",
    "nordpass",
    "protonpass",
    "seahorse",
    "kwalletmanager5",
    "kwalletmanager",
    "gnome-keyring-daemon",
    "pinentry",
    "pinentry-gtk-2",
    "pinentry-gnome3",
    "pinentry-qt",
    "pinentry-curses",
}


def _bare(name: str) -> str:
    name = str(name or "").strip().lower()
    return name[:-4] if name.endswith(".exe") else name


class AutoCopy(QObject):
    """Same surface as autocopy.AutoCopy, backed by the primary selection."""

    # (text, kind); kind is always "selection" here: the selection does not
    # say whether it came from a drag or a double-click.
    copied = Signal(str, str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._engaged = False
        self._paused = False
        self._last_text: str | None = None
        self._clipboard = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._capture)

    # -- lifecycle ---------------------------------------------------------
    @property
    def supported(self) -> bool:
        clipboard = QGuiApplication.clipboard()
        return clipboard is not None and clipboard.supportsSelection()

    @property
    def engaged(self) -> bool:
        return self._engaged

    def configure(self, cfg: dict) -> None:
        self._cfg = cfg

    def engage(self) -> None:
        if self._engaged:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None or not clipboard.supportsSelection():
            raise AutoCopyError(
                "this desktop has no primary selection to follow (on Wayland, "
                "copy on select is not available yet)"
            )
        if shutil.which("xprop") is None:
            # Without it nothing can tell a password manager from a terminal,
            # and copying blind is the one thing the block list exists to stop.
            raise AutoCopyError(
                "it needs xprop to skip password managers; install it with  "
                "sudo apt install x11-utils"
            )
        self._clipboard = clipboard
        clipboard.selectionChanged.connect(self._on_selection_changed)
        # What is already selected was not selected while this was on.
        self._last_text = clipboard.text(QClipboard.Mode.Selection) or None
        self._engaged = True

    def release(self) -> None:
        if self._clipboard is not None:
            try:
                self._clipboard.selectionChanged.disconnect(self._on_selection_changed)
            except (RuntimeError, TypeError):
                pass
        self._clipboard = None
        self._settle.stop()
        self._engaged = False
        self._last_text = None

    def pause(self) -> None:
        self._paused = True
        self._settle.stop()

    def resume(self) -> None:
        self._paused = False

    # -- the copy ----------------------------------------------------------
    def _on_selection_changed(self) -> None:
        if self._engaged and not self._paused:
            self._settle.start()

    def _capture(self) -> None:
        if not self._engaged or self._paused or self._clipboard is None:
            return
        text = self._clipboard.text(QClipboard.Mode.Selection)
        if not text or not text.strip():
            return
        if self._cfg.get("auto_copy_dedupe", True) and text == self._last_text:
            return
        process = active_process()
        if process is None or process == "own" or self.is_blocked(process):
            # None: the program in front could not be identified, so the block
            # list cannot be applied. Skip this one rather than guess.
            return
        self._last_text = text
        self._clipboard.setText(text, QClipboard.Mode.Clipboard)
        self.copied.emit(text, "selection")

    def is_blocked(self, process: str) -> bool:
        """Password managers, and whatever is in Never copy from, by bare name."""
        name = _bare(process)
        blocked = {_bare(n) for n in BLOCKED_PROCESSES} | LINUX_BLOCKED
        extra = self._cfg.get("auto_copy_extra_blocked") or ()
        if isinstance(extra, str):
            extra = [extra]
        blocked |= {_bare(n) for n in extra}
        return name in blocked


# -- which program is in front ------------------------------------------------
_WINDOW_ID = re.compile(r"0x[0-9a-fA-F]+")
_PID = re.compile(r"=\s*(\d+)")


def _xprop(*args: str) -> str:
    if shutil.which("xprop") is None:
        return ""
    try:
        done = subprocess.run(
            ["xprop", *args], capture_output=True, text=True, timeout=_PROCESS_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _process_of_window(window: str) -> str | None:
    """The process name behind an X11 window id, "own" for ShadowSnip's own."""
    match = _PID.search(_xprop("-id", window, "_NET_WM_PID"))
    if not match:
        return None
    pid = int(match.group(1))
    if pid == os.getpid():
        return "own"
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
            return fh.read().strip().lower() or None
    except OSError:
        return None


def active_process() -> str | None:
    """The process name of the focused window, or None when it cannot be told.

    Uses `xprop`, which Kali and most X11 desktops ship. None means the block
    list cannot be applied, and the caller then does not copy.
    """
    match = _WINDOW_ID.search(_xprop("-root", "_NET_ACTIVE_WINDOW"))
    if not match or int(match.group(0), 16) == 0:
        return None
    return _process_of_window(match.group(0))


def foreground_process() -> str | None:
    """For Settings' Pick an app: the program in front, never ShadowSnip."""
    process = active_process()
    return None if process in (None, "own") else process


def last_other_process() -> str | None:
    """For Settings' Block the app I was just in: the topmost window not ours.

    _NET_CLIENT_LIST_STACKING lists windows bottom to top, so it is walked
    from the end.
    """
    stacking = _WINDOW_ID.findall(_xprop("-root", "_NET_CLIENT_LIST_STACKING"))
    for window in reversed(stacking):
        process = _process_of_window(window)
        if process and process != "own":
            return process
    return None
