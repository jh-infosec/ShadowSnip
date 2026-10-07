"""The one place that picks the Windows or the Linux implementation.

Everything platform-specific lives in its own module:

    Windows   hotkey.py        RegisterHotKey and a native event filter
              autocopy.py      low-level mouse hook and a synthetic Ctrl+C
    Linux     hotkey_linux.py  the desktop's own shortcuts (Xfce set for you)
              autocopy_linux.py  the X11 primary selection

The Windows modules are the original code, unchanged; Linux support was added
beside them rather than by reworking them. app.py and settings_dialog.py take
these names from here and never test the platform themselves.
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if IS_LINUX:
    import autocopy_linux as _autocopy
    import hotkey_linux as _hotkey
else:
    import autocopy as _autocopy
    import hotkey as _hotkey

HotkeyManager = _hotkey.HotkeyManager
AutoCopy = _autocopy.AutoCopy
foreground_process = _autocopy.foreground_process
last_other_process = _autocopy.last_other_process

# What the platform calls the thing a process is named by, for Settings text.
PROGRAM_NAME_HINT = "process name, e.g. keepassxc" if IS_LINUX else "executable name, e.g. lightroom.exe"
