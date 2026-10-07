"""ShadowSnip entry point.

    python main.py           start in the tray
    python main.py --snip    start and take a snip straight away, or hand the
                             request to the copy that is already running
    python main.py --tray    start quietly in the tray, without the window;
                             for the run-at-login shortcut
    python main.py --note    jot a note into the running lab (what the Linux
                             quick-note shortcut runs)

Started normally (double-clicking the .exe, the Start menu, a taskbar pin) it
opens the window, so there is something to see that it has started.

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
    quiet = "--tray" in sys.argv[1:]
    request = b"snip" if want_snip else b"note" if want_note else b"show"
    _set_dpi_awareness()

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
