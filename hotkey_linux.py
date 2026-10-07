"""Global hotkeys on Linux, by asking the desktop to own them.

Windows lets an application register a system-wide hotkey (hotkey.py). X11
has no equivalent that is both reliable and polite: grabbing keys directly
fights the desktop's own shortcuts, and Wayland does not allow it at all. The
desktop already has a keyboard-shortcut system, so ShadowSnip uses that: the
shortcut runs ShadowSnip again with `--snip` or `--note`, and the copy that is
already running takes the request over its local socket (main.py).

On Xfce (Kali's default desktop) this is done for you: registering writes the
shortcut into Xfce's settings through `xfconf-query`, and it takes effect
immediately. A combination Xfce already uses for something else is reported
as taken, the same way Windows reports one taken by another program, and is
never overwritten. On other desktops, registering explains the one shortcut
to add by hand.

The manager has the same surface as the Windows one (register, unregister,
spec, registered, supported, triggered) so app.py does not care which it has.
`triggered` is never emitted here: the request arrives through main.py.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from hotkey import _MODIFIERS, HotkeyError, describe

XFCE_CHANNEL = "xfce4-keyboard-shortcuts"
XFCE_PREFIX = "/commands/custom/"

# The command-line flag each action is reached by.
ACTION_FLAGS = {"snip": "--snip", "note": "--note"}

_XFCE_MODIFIERS = {
    "ctrl": "<Primary>",
    "control": "<Primary>",
    "alt": "<Alt>",
    "shift": "<Shift>",
    "win": "<Super>",
    "super": "<Super>",
    "meta": "<Super>",
}
# Key names as Xfce (GTK) spells them.
_XFCE_KEYS = {
    "prtsc": "Print",
    "printscreen": "Print",
    "print": "Print",
    "insert": "Insert",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "space": "space",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "BackSpace",
    "enter": "Return",
    "return": "Return",
    "left": "Left",
    "up": "Up",
    "right": "Right",
    "down": "Down",
}
for _n in range(1, 25):
    _XFCE_KEYS[f"f{_n}"] = f"F{_n}"


def xfce_accelerator(spec: str) -> str:
    """'ctrl+shift+s' -> '<Primary><Shift>s', in Xfce's fixed modifier order."""
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        raise HotkeyError("empty hotkey")
    mods: list[str] = []
    key = None
    for part in parts:
        if part in _MODIFIERS:
            tag = _XFCE_MODIFIERS[part]
            if tag not in mods:
                mods.append(tag)
        elif key is None:
            key = part
        else:
            raise HotkeyError(f"more than one key in '{spec}'")
    if key is None:
        raise HotkeyError(f"'{spec}' has modifiers but no key")
    if key in _XFCE_KEYS:
        name = _XFCE_KEYS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        name = key
    else:
        raise HotkeyError(f"unknown key '{key}'")
    order = ["<Primary>", "<Shift>", "<Alt>", "<Super>"]
    return "".join(sorted(mods, key=order.index)) + name


def launch_command(flag: str) -> str:
    """The shell command that reaches this install of ShadowSnip with `flag`.

    A frozen build is its own executable; from source it is this Python
    running main.py. Both are quoted, because the project lives in a folder
    with a space in it on more than one machine.
    """
    if getattr(sys, "frozen", False):
        parts = [sys.executable, flag]
    else:
        main = Path(__file__).resolve().with_name("main.py")
        parts = [sys.executable, str(main), flag]
    return " ".join(shlex.quote(part) for part in parts)


def is_xfce() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get(
        "DESKTOP_SESSION", ""
    )
    return "xfce" in desktop.lower() and shutil.which("xfconf-query") is not None


def _xfconf(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["xfconf-query", "-c", XFCE_CHANNEL, *args],
        capture_output=True,
        text=True,
        timeout=5,
    )


class HotkeyManager(QObject):
    """Desktop-owned shortcuts that run ShadowSnip with --snip or --note."""

    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._specs: dict[str, str] = {}  # action name -> spec
        self._paths: dict[str, str] = {}  # action name -> xfconf property

    @property
    def supported(self) -> bool:
        return is_xfce()

    def spec(self, name: str = "snip") -> str:
        return self._specs.get(name, "")

    def registered(self, name: str = "snip") -> bool:
        return name in self._specs

    def register(self, app, spec: str, name: str = "snip") -> None:
        """Bind `spec` to this action in the desktop's shortcuts.

        Raises HotkeyError when the combination is malformed, already bound to
        something else, or when this desktop's shortcuts cannot be set from
        here (the message then says what to add by hand).
        """
        accelerator = xfce_accelerator(spec)
        flag = ACTION_FLAGS.get(name)
        if flag is None:
            raise HotkeyError(f"no command-line flag for the '{name}' action")
        command = launch_command(flag)

        if not is_xfce():
            raise HotkeyError(
                f"{describe(spec)} has to be set in your desktop's keyboard "
                f"settings on this desktop: add a shortcut that runs  {command}"
            )

        path = XFCE_PREFIX + accelerator
        try:
            current = _xfconf("-p", path)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HotkeyError(f"Xfce's shortcut settings could not be read ({exc})") from exc
        existing = current.stdout.strip() if current.returncode == 0 else ""
        if existing and existing != command and not _is_ours(existing):
            raise HotkeyError(
                f"{describe(spec)} is already used in Xfce for: {existing}"
            )

        self.unregister(name)
        if existing != command:
            try:
                done = _xfconf("-p", path, "-n", "-t", "string", "-s", command)
            except (OSError, subprocess.SubprocessError) as exc:
                raise HotkeyError(f"the Xfce shortcut could not be set ({exc})") from exc
            if done.returncode != 0:
                raise HotkeyError(
                    f"the Xfce shortcut could not be set: {done.stderr.strip() or 'unknown error'}"
                )
        self._specs[name] = spec
        self._paths[name] = path

    def unregister(self, name: str | None = None) -> None:
        """Remove the shortcuts this manager set, never anyone else's.

        Quitting ShadowSnip does not call this for every action: the shortcut
        staying in Xfce is what lets it start ShadowSnip and snip in one press.
        It is called when a hotkey is changed in Settings, to remove the old
        combination.
        """
        targets = list(self._specs) if name is None else [name]
        for target in targets:
            path = self._paths.pop(target, None)
            self._specs.pop(target, None)
            if not path or not is_xfce():
                continue
            try:
                current = _xfconf("-p", path)
                if current.returncode == 0 and _is_ours(current.stdout.strip()):
                    _xfconf("-p", path, "-r")
            except (OSError, subprocess.SubprocessError):
                pass

    def release_all(self) -> None:
        """Forget registrations without touching the desktop's settings."""
        self._specs.clear()
        self._paths.clear()


def _is_ours(command: str) -> bool:
    """A shortcut command this or another ShadowSnip install wrote.

    Deliberately narrow, because a match is what lets ShadowSnip replace or
    remove a shortcut: the exact command this install writes, or a command
    that names ShadowSnip and ends in one of its flags. Something like
    `python main.py --snip` from another tool is not ours and is left alone.
    """
    command = command.strip()
    if command in {launch_command(flag) for flag in ACTION_FLAGS.values()}:
        return True
    lowered = command.lower()
    ends_with_flag = any(lowered.endswith(" " + flag) for flag in ACTION_FLAGS.values())
    return ends_with_flag and "shadowsnip" in lowered
