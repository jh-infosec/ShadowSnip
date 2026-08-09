"""ShadowSnip entry point.

    python main.py           start in the tray
    python main.py --snip    start and take a snip straight away, or hand the
                             request to the copy that is already running

Only one copy runs at a time; a second launch wakes the first one instead.
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


def _hand_off_to_running_instance(want_snip: bool) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(IPC_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"snip" if want_snip else b"ping")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def main() -> int:
    want_snip = "--snip" in sys.argv[1:]
    _set_dpi_awareness()

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.APP_NAME)
    app.setWindowIcon(build_icon())
    app.setQuitOnLastWindowClosed(False)

    if _hand_off_to_running_instance(want_snip):
        return 0

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
            if payload.startswith(b"snip"):
                shadow.request_snip()
            conn.disconnectFromServer()

        conn.readyRead.connect(_read)

    server.newConnection.connect(_on_connection)

    if want_snip:
        QTimer.singleShot(200, shadow.request_snip)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
