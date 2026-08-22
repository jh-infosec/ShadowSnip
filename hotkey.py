"""System-wide hotkey handling.

Uses the Win32 RegisterHotKey API and a Qt native event filter, so no
keyboard hook and no administrator rights are needed. Hotkey strings look
like "ctrl+shift+s", "win+shift+x" or "prtsc".
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

_NAMED_KEYS = {
    "prtsc": 0x2C,
    "printscreen": 0x2C,
    "print": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "space": 0x20,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "enter": 0x0D,
    "return": 0x0D,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}
for _n in range(1, 25):
    _NAMED_KEYS[f"f{_n}"] = 0x6F + _n


class HotkeyError(RuntimeError):
    pass


def parse(spec: str) -> tuple[int, int]:
    """Turn "ctrl+shift+s" into (modifier mask, virtual key code)."""
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        raise HotkeyError("empty hotkey")

    mods = 0
    key = None
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif key is None:
            key = part
        else:
            raise HotkeyError(f"more than one key in '{spec}'")

    if key is None:
        raise HotkeyError(f"'{spec}' has modifiers but no key")

    if key in _NAMED_KEYS:
        code = _NAMED_KEYS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        code = ord(key.upper())
    else:
        raise HotkeyError(f"unknown key '{key}'")

    return mods | MOD_NOREPEAT, code


def describe(spec: str) -> str:
    """Pretty form for menus: 'ctrl+shift+s' -> 'Ctrl+Shift+S'."""
    pretty = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    out = []
    for part in str(spec).split("+"):
        part = part.strip().lower()
        if not part:
            continue
        out.append(pretty.get(part, part.upper() if len(part) == 1 else part.capitalize()))
    return "+".join(out)


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers named hotkeys and emits `triggered(name)` when one fires.

    Several hotkeys share one native event filter rather than one filter each.
    The filter is called for every message the application receives, so it is
    the hot path of the whole process, and paying for a second Python callback
    on every mouse move to save a dictionary lookup would be a poor trade.
    """

    triggered = Signal(str)

    BASE_ID = 0xA51

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._installed = False
        self._ids: dict[str, int] = {}  # action name -> Win32 hotkey id
        self._specs: dict[str, str] = {}  # action name -> registered spec

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    def spec(self, name: str = "snip") -> str:
        """The spec currently registered for an action, or ""."""
        return self._specs.get(name, "")

    def registered(self, name: str = "snip") -> bool:
        return name in self._specs

    def register(self, app, spec: str, name: str = "snip") -> None:
        """Replace this action's registration. Raises HotkeyError on failure."""
        mods, key = parse(spec)
        if not self.supported:
            raise HotkeyError("global hotkeys are only wired up on Windows")

        self.unregister(name)
        if not self._installed:
            app.installNativeEventFilter(self)
            self._installed = True

        hotkey_id = self._id_for(name)
        if not ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, key):
            raise HotkeyError(
                f"{describe(spec)} is already taken by another program"
            )
        self._specs[name] = spec

    def unregister(self, name: str | None = None) -> None:
        """Drop one action's hotkey, or every one of them when name is None."""
        targets = list(self._specs) if name is None else [name]
        for target in targets:
            if target in self._specs and self.supported:
                try:
                    ctypes.windll.user32.UnregisterHotKey(None, self._ids[target])
                except OSError:
                    pass
            self._specs.pop(target, None)

    def _id_for(self, name: str) -> int:
        """A stable Win32 id per action name, handed out in first-seen order.

        Kept even after unregistering, so re-registering the same action does
        not leak ids on every settings save.
        """
        if name not in self._ids:
            self._ids[name] = self.BASE_ID + len(self._ids)
        return self._ids[name]

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY:
            for name, hotkey_id in self._ids.items():
                if msg.wParam == hotkey_id and name in self._specs:
                    self.triggered.emit(name)
                    return True, 0
        return False, 0


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]
