"""Start ShadowSnip when you sign in (0.20.0): the Settings switch behind it.

| System  | What the switch writes                                                      |
|---------|-----------------------------------------------------------------------------|
| Windows | `ShadowSnip.lnk` in your Startup folder (shell:startup), running it with --tray |
| Linux   | `shadowsnip.desktop` in ~/.config/autostart, the file `install.sh --autostart` writes |

Both are ordinary per-user entries, the same ones you would make by hand
(BUILD.md), and both start ShadowSnip in the tray: main.py already treats a
start from the Startup folder as a login start. Turning the switch off
deletes the entry again. Nothing else is changed, and nothing needs admin
rights.

The switch shows what is really there, not a saved setting, so an entry
made by hand or by install.sh shows as on, and one deleted by hand as off.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

ENTRY_NAME = "ShadowSnip"
TRAY_FLAG = "--tray"


class AutostartError(OSError):
    pass


# -- where the entry lives ------------------------------------------------------------------
def windows_startup_folder() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def linux_autostart_folder() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart"


def entry_path() -> Path:
    if sys.platform == "win32":
        return windows_startup_folder() / f"{ENTRY_NAME}.lnk"
    return linux_autostart_folder() / "shadowsnip.desktop"


# -- what it runs --------------------------------------------------------------------------------
def program() -> list[str]:
    """How to start this copy of ShadowSnip: the built program, or Python and main.py.

    On Linux the `shadowsnip` launcher is used when it is on the PATH (the one
    install.sh or the .deb puts there), since it also sets up the binary's
    environment.
    """
    if sys.platform != "win32":
        launcher = shutil.which("shadowsnip")
        if launcher:
            return [launcher]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    python = sys.executable
    if sys.platform == "win32":
        # pythonw: no console window at login.
        candidate = Path(python).with_name("pythonw.exe")
        if candidate.is_file():
            python = str(candidate)
    return [python, str(Path(__file__).resolve().with_name("main.py"))]


def _icon() -> str:
    here = Path(__file__).resolve().parent
    for candidate in (here / "shadowsnip.png", Path(sys.executable).with_name("shadowsnip.png")):
        if candidate.is_file():
            return str(candidate)
    return "shadowsnip"


def desktop_entry(command: list[str]) -> str:
    """The Linux autostart entry, in the same shape install.sh writes."""
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=ShadowSnip",
        "GenericName=Screenshot and pentest evidence tool",
        "Comment=Snip, file evidence into labs, and build the writeup as you go",
        "Exec=" + " ".join(shlex.quote(part) for part in [*command, TRAY_FLAG]),
        f"Icon={_icon()}",
        "Terminal=false",
        "Categories=Utility;Graphics;Security;",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true",
        "",
    ])


# -- the switch -----------------------------------------------------------------------------------
def is_enabled() -> bool:
    path = entry_path()
    if not path.is_file():
        return False
    if sys.platform == "win32":
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # An entry someone turned off in their desktop's own settings.
    return "Hidden=true" not in text and "X-GNOME-Autostart-enabled=false" not in text


def _write_windows_shortcut(path: Path, command: list[str]) -> None:
    try:
        from win32com.client import Dispatch
    except ImportError as exc:
        raise AutostartError("Making the Startup shortcut needs pywin32 (pip install -r requirements.txt).") from exc
    shell = Dispatch("WScript.Shell")
    link = shell.CreateShortCut(str(path))
    link.Targetpath = command[0]
    link.Arguments = " ".join([*(f'"{part}"' for part in command[1:]), TRAY_FLAG])
    link.WorkingDirectory = str(Path(command[-1]).parent if len(command) > 1 else Path(command[0]).parent)
    icon = Path(command[0]) if getattr(sys, "frozen", False) else Path(__file__).with_name("shadowsnip.ico")
    if icon.is_file():
        link.IconLocation = str(icon)
    link.Description = "ShadowSnip, started in the tray at sign-in"
    link.save()


def enable() -> Path:
    """Start ShadowSnip in the tray at sign-in. Returns the entry written."""
    path = entry_path()
    command = program()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            _write_windows_shortcut(path, command)
        else:
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(desktop_entry(command), encoding="utf-8")
            os.replace(temp, path)
    except OSError as exc:
        raise AutostartError(f"Could not write {path}: {exc}") from exc
    return path


def disable() -> None:
    path = entry_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise AutostartError(f"Could not remove {path}: {exc}") from exc


def set_enabled(on: bool) -> None:
    if on:
        enable()
    else:
        disable()


def describe() -> str:
    """Where the entry is, for the Settings tooltip."""
    return str(entry_path())
