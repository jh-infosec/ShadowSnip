"""ShadowSnip entry point.

    python main.py           start in the tray
    python main.py --snip    start and take a snip straight away, or hand the
                             request to the copy that is already running

Only one copy runs at a time; a second launch wakes the first one instead.
Launching it again (the taskbar pin, the Start menu, the .exe) brings the
window up in the copy that is already running, and with --snip starts a snip
there. The running copy answers, so a copy that is running but stuck is
reported instead of the launch silently doing nothing.
"""

from __future__ import annotations

import ctypes
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


def _hand_off_to_running_instance(want_snip: bool) -> str:
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
    socket.write(b"snip" if want_snip else b"show")
    socket.waitForBytesWritten(300)
    answered = socket.waitForReadyRead(2000) and bytes(
        socket.readAll().data()
    ).startswith(ACK)
    socket.disconnectFromServer()
    return "done" if answered else "stuck"


def main() -> int:
    want_snip = "--snip" in sys.argv[1:]
    _set_dpi_awareness()

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.APP_NAME)
    app.setWindowIcon(build_icon())
    app.setQuitOnLastWindowClosed(False)

    handed_off = _hand_off_to_running_instance(want_snip)
    if handed_off == "done":
        return 0
    if handed_off == "stuck":
        QMessageBox.warning(
            None,
            config.APP_NAME,
            "ShadowSnip is already running but did not respond. End "
            "ShadowSnip.exe (or pythonw.exe) in Task Manager, then start it "
            "again.",
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
            else:
                shadow.show_window()
            conn.write(ACK)
            conn.flush()
            conn.disconnectFromServer()

        conn.readyRead.connect(_read)

    server.newConnection.connect(_on_connection)

    if want_snip:
        QTimer.singleShot(200, shadow.request_snip)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
