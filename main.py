"""ShadowSnip entry point.

    python main.py           start in the tray
    python main.py --snip    start and take a snip straight away, or hand the
                             request to the copy that is already running
    python main.py --tray    start quietly in the tray, without the window;
                             for the run-at-login shortcut
    python main.py --show    always open the window, even straight after login
    python main.py --note    jot a note into the running lab (what the Linux
                             quick-note shortcut runs)

Started normally (double-clicking the .exe, the Start menu, a taskbar pin) it
opens the window, so there is something to see that it has started.

Started by Windows at login it stays in the tray, with or without --tray
(0.8.0). Before, a login shortcut without --tray, a Run entry, or Windows
reopening its "restartable apps" brought the window up after every reboot.
A login start is recognised by:

- the shortcut it was started from sitting in a Startup folder (Windows
  passes the shortcut's path to the program it starts), or
- having been started without any shortcut in the first few minutes after
  you signed in (a Run entry, a scheduled task, restarted apps).

A shortcut anywhere else (taskbar pin, Start menu, desktop) always opens the
window, so starting it by hand right after login still shows it.

Only one copy runs at a time; a second launch wakes the first one instead.
Launching it again (the taskbar pin, the Start menu, the .exe) brings the
window up in the copy that is already running, and with --snip starts a snip
there. The running copy answers, so a copy that is running but stuck is
reported instead of the launch silently doing nothing.
"""

from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

import config
from app import ShadowSnipApp, build_icon

IPC_NAME = "ShadowSnip.instance"
# ASFW_ANY: let whichever process answers take the foreground.
_ASFW_ANY = -1
# The running copy answers with this once it has acted on the request.
ACK = b"ok"


def _allow_foreground_handoff() -> None:
    """Pass this launch's right to take the foreground on to the running copy.

    Windows only lets the process the user just clicked bring a window to the
    front. That is this short-lived second launch, not the copy in the tray, so
    without handing the right over the window opens behind everything else, or
    only flashes its taskbar button.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)
    except (AttributeError, OSError):
        pass


def _set_dpi_awareness() -> None:
    """Per-monitor DPI awareness, so grabs are not blurry on scaled displays."""
    if sys.platform != "win32":
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def wayland_warning(env=None) -> str:
    """The startup warning for a Wayland session, or "" when there is none.

    Wayland does not let an application read the screen, so a snip there is
    black or shows only some windows. Saying so once at startup beats a
    silently black snip. X11, which Kali's Xfce uses by default, is fine.
    """
    env = os.environ if env is None else env
    if not sys.platform.startswith("linux"):
        return ""
    if str(env.get("XDG_SESSION_TYPE", "")).lower() != "wayland":
        return ""
    return (
        "This is a Wayland session. Wayland does not let ShadowSnip capture "
        "the screen, so snips may come out black. Log in with an X11 (Xorg) "
        "session to use it; Kali's default Xfce session is X11."
    )


# Started this soon after sign-in, with no shortcut, counts as started by Windows.
LOGIN_WINDOW_SECONDS = 180
_STARTF_TITLEISLINKNAME = 0x800


def _launch_shortcut() -> str | None:
    """The .lnk this process was started from, "" for none, None if unknown.

    Explorer passes a shortcut's own path in STARTUPINFO when it starts the
    program a shortcut points at.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
            ]

        info = STARTUPINFOW()
        info.cb = ctypes.sizeof(info)
        ctypes.windll.kernel32.GetStartupInfoW(ctypes.byref(info))
        if info.dwFlags & _STARTF_TITLEISLINKNAME and info.lpTitle:
            return info.lpTitle
        return ""
    except (AttributeError, OSError, ValueError):
        return None


def _seconds_since_logon() -> float | None:
    """How long ago this Windows session was signed in to, or None if unknown."""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        class WTSINFOW(ctypes.Structure):
            _fields_ = [
                ("State", ctypes.c_int), ("SessionId", wintypes.DWORD),
                ("IncomingBytes", wintypes.DWORD), ("OutgoingBytes", wintypes.DWORD),
                ("IncomingFrames", wintypes.DWORD), ("OutgoingFrames", wintypes.DWORD),
                ("IncomingCompressedBytes", wintypes.DWORD),
                ("OutgoingCompressedBytes", wintypes.DWORD),
                ("WinStationName", wintypes.WCHAR * 32), ("Domain", wintypes.WCHAR * 17),
                ("UserName", wintypes.WCHAR * 21),
                ("ConnectTime", ctypes.c_longlong), ("DisconnectTime", ctypes.c_longlong),
                ("LastInputTime", ctypes.c_longlong), ("LogonTime", ctypes.c_longlong),
                ("CurrentTime", ctypes.c_longlong),
            ]

        wtsapi = ctypes.windll.wtsapi32
        buffer = ctypes.c_void_p()
        size = wintypes.DWORD()
        ok = wtsapi.WTSQuerySessionInformationW(
            None, wintypes.DWORD(0xFFFFFFFF), 24,  # current session, WTSSessionInfo
            ctypes.byref(buffer), ctypes.byref(size),
        )
        if not ok or not buffer:
            raise OSError("WTSQuerySessionInformation failed")
        try:
            info = ctypes.cast(buffer, ctypes.POINTER(WTSINFOW)).contents
            if info.LogonTime > 0 and info.CurrentTime >= info.LogonTime:
                return (info.CurrentTime - info.LogonTime) / 10_000_000
        finally:
            wtsapi.WTSFreeMemory(buffer)
    except (AttributeError, OSError, ValueError):
        pass
    try:
        # Fallback: time since the computer started.
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return ctypes.windll.kernel32.GetTickCount64() / 1000
    except (AttributeError, OSError):
        return None


def started_at_login(argv, shortcut=None, since_logon=None) -> bool:
    """Whether this launch came from Windows signing in rather than from you.

    `shortcut` and `since_logon` are what `_launch_shortcut` and
    `_seconds_since_logon` return; passed in for testing.
    """
    args = list(argv)
    if "--show" in args:
        return False
    if "--tray" in args:
        return True
    if shortcut:
        folder = shortcut.replace("/", "\\").lower()
        return "\\start menu\\programs\\startup\\" in folder
    if shortcut == "" and since_logon is not None:
        return since_logon < LOGIN_WINDOW_SECONDS
    return False


def request_for(want_snip: bool, want_note: bool, quiet: bool) -> bytes:
    """What this launch asks a copy that is already running to do."""
    if want_snip:
        return b"snip"
    if want_note:
        return b"note"
    # A quiet start that finds a copy already running asks it for nothing, so
    # two login entries never bring the window up between them.
    return b"tray" if quiet else b"show"


def _opt_out_of_restart_apps() -> None:
    """Never be reopened by Windows' "restart apps after signing in"."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.UnregisterApplicationRestart()
    except (AttributeError, OSError):
        pass


def _hand_off_to_running_instance(request: bytes) -> str:
    """Ask a copy that is already running to act. Returns what happened.

    "none"      nothing is listening, so this launch should become the app
    "done"      the running copy answered
    "stuck"     something is listening but did not answer in time
    """
    socket = QLocalSocket()
    socket.connectToServer(IPC_NAME)
    if not socket.waitForConnected(300):
        return "none"
    _allow_foreground_handoff()
    socket.write(request)
    socket.waitForBytesWritten(300)
    answered = socket.waitForReadyRead(2000) and bytes(
        socket.readAll().data()
    ).startswith(ACK)
    socket.disconnectFromServer()
    return "done" if answered else "stuck"


def main() -> int:
    want_snip = "--snip" in sys.argv[1:]
    want_note = "--note" in sys.argv[1:] and not want_snip
    quiet = not (want_snip or want_note) and started_at_login(
        sys.argv[1:], _launch_shortcut(), _seconds_since_logon()
    )
    request = request_for(want_snip, want_note, quiet)
    _set_dpi_awareness()
    _opt_out_of_restart_apps()

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.APP_NAME)
    app.setWindowIcon(build_icon())
    app.setQuitOnLastWindowClosed(False)

    handed_off = _hand_off_to_running_instance(request)
    if handed_off == "done":
        return 0
    if handed_off == "stuck":
        QMessageBox.warning(
            None,
            config.APP_NAME,
            "ShadowSnip is already running but did not respond. End "
            "ShadowSnip.exe (or pythonw.exe) in Task Manager, then start it "
            "again."
            if sys.platform == "win32"
            else "ShadowSnip is already running but did not respond. End it "
            "with  pkill -x ShadowSnip  (or end the python process running "
            "main.py, when running from source), then start it again.",
        )
        return 1

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            config.APP_NAME,
            "There is no system tray on this desktop, so ShadowSnip has "
            "nowhere to live. Start it with --snip for a one-shot capture.",
        )

    shadow = ShadowSnipApp(app)
    warning = wayland_warning()
    if warning:
        shadow.tray.showMessage(
            config.APP_NAME, warning, QSystemTrayIcon.MessageIcon.Warning, 10000
        )

    QLocalServer.removeServer(IPC_NAME)
    server = QLocalServer()
    server.listen(IPC_NAME)

    def _on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def _read():
            payload = bytes(conn.readAll().data())
            # Anything that is not a snip request is a plain relaunch, which
            # should bring the window up. Before 0.4.4 it was ignored, so
            # clicking the taskbar pin while ShadowSnip was already in the
            # tray did nothing at all.
            if payload.startswith(b"snip"):
                shadow.request_snip()
            elif payload.startswith(b"note"):
                shadow.quick_note()
            elif payload.startswith(b"tray"):
                pass  # a login start that found this copy running: stay put
            else:
                shadow.show_window()
            conn.write(ACK)
            conn.flush()
            conn.disconnectFromServer()

        conn.readyRead.connect(_read)

    server.newConnection.connect(_on_connection)

    if want_snip:
        QTimer.singleShot(200, shadow.request_snip)
    elif want_note:
        QTimer.singleShot(200, shadow.quick_note)
    elif not quiet:
        # Launched by hand: show the window. Before 0.4.8 a fresh start went
        # straight to the tray, which looked like nothing had happened.
        QTimer.singleShot(0, shadow.show_window)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
