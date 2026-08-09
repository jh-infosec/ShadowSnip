"""Tray application and the snip pipeline.

Pipeline for one snip:

    freeze screens -> overlay -> crop -> compress -> clipboard -> disk -> preview

The clipboard and disk writes both happen automatically. Everything in the
preview window afterwards is optional.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRect, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

import capture
import clipboard
import config
import hotkey as hotkey_mod
import imageops
import storage
from overlay import SelectionController
from preview import PreviewWindow
from settings_dialog import SettingsDialog


class ShadowSnipApp(QObject):
    def __init__(self, qapp, parent=None):
        super().__init__(parent)
        self.qapp = qapp
        self.cfg = config.load()
        self.busy = False
        self.controller: SelectionController | None = None
        self._grabs = []
        self._last_png = b""
        self._last_image = None

        self.preview = PreviewWindow()
        self.preview.new_snip_requested.connect(self.request_snip)

        self.tray = QSystemTrayIcon(build_icon(), self)
        self.tray.setToolTip("ShadowSnip")
        self.tray.activated.connect(self._on_tray_activated)
        self._build_menu()
        self.tray.show()

        self.hotkeys = hotkey_mod.HotkeyManager(self)
        self.hotkeys.triggered.connect(self.request_snip)
        self._register_hotkey(startup=True)

    # -- tray --------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = QMenu()
        self.action_new = QAction("New snip", self)
        self.action_new.triggered.connect(self.request_snip)
        menu.addAction(self.action_new)

        action_folder = QAction("Open save folder", self)
        action_folder.triggered.connect(self._open_save_folder)
        menu.addAction(action_folder)

        menu.addSeparator()
        action_settings = QAction("Settings...", self)
        action_settings.triggered.connect(self.open_settings)
        menu.addAction(action_settings)

        action_quit = QAction("Quit ShadowSnip", self)
        action_quit.triggered.connect(self.quit)
        menu.addAction(action_quit)

        self.tray.setContextMenu(menu)
        self._refresh_menu_text()

    def _refresh_menu_text(self) -> None:
        label = hotkey_mod.describe(self.cfg["hotkey"])
        self.action_new.setText(f"New snip\t{label}")
        self.tray.setToolTip(f"ShadowSnip - press {label} to snip")

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.request_snip()

    def _open_save_folder(self) -> None:
        folder = storage.save_dir(self.cfg)
        storage.reveal(folder / f"{self.cfg['latest_name']}.{self.cfg['disk_format']}")

    # -- hotkey ------------------------------------------------------------
    def _register_hotkey(self, startup: bool = False) -> None:
        try:
            self.hotkeys.register(self.qapp, self.cfg["hotkey"])
        except hotkey_mod.HotkeyError as exc:
            self.tray.showMessage(
                "ShadowSnip",
                f"Hotkey not active: {exc}. Snip from the tray icon, or pick "
                "another combination in Settings.",
                QSystemTrayIcon.MessageIcon.Warning,
                6000,
            )
        else:
            if not startup:
                self._refresh_menu_text()

    # -- snipping ----------------------------------------------------------
    def request_snip(self) -> None:
        if self.busy:
            return
        self.busy = True
        was_visible = self.preview.isVisible()
        if was_visible:
            self.preview.hide()
        # Give the compositor a moment to actually remove our own window
        # before the screen is frozen.
        QTimer.singleShot(140 if was_visible else 0, self._begin_snip)

    def _begin_snip(self) -> None:
        grabs = capture.grab_all_screens()
        if not grabs:
            self.busy = False
            self._warn("No screen could be captured.")
            return
        self._grabs = grabs
        self.controller = SelectionController(grabs, self.cfg["dim_opacity"], self)
        self.controller.selected.connect(self._on_selected)
        self.controller.cancelled.connect(self._on_cancelled)
        self.controller.start()

    def _on_cancelled(self) -> None:
        self.controller = None
        self._grabs = []
        self.busy = False

    def _on_selected(self, rect: QRect) -> None:
        self.controller = None
        grabs, self._grabs = self._grabs, []
        try:
            image = capture.compose_selection(grabs, rect)
            if image is None:
                return
            self._handle_snip(image)
        finally:
            self.busy = False

    def _handle_snip(self, image) -> None:
        result = imageops.process(image, self.cfg)
        self._last_png = result.png
        self._last_image = result.image

        notes = []
        try:
            clipboard.copy(
                result.png,
                result.image,
                include_dib=self.cfg["clipboard_dib_fallback"],
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user
            notes.append(f"clipboard failed ({exc})")

        latest_path: Path | None = None
        try:
            latest_path = storage.save_latest(
                result.disk.data, result.disk.ext, self.cfg
            )
            storage.save_history(result.disk.data, result.disk.ext, self.cfg)
        except OSError as exc:
            notes.append(f"could not write to the save folder ({exc})")

        status = self._status_line(result, latest_path, notes)
        if self.cfg["show_preview"]:
            self.preview.show_snip(
                image=image,
                disk_bytes=result.disk.data,
                ext=result.disk.ext,
                latest_path=latest_path,
                status=status,
                copy_again=self._copy_again,
            )
        else:
            self.tray.showMessage("ShadowSnip", status, build_icon(), 3000)

    def _status_line(self, result, latest_path, notes) -> str:
        width, height = result.source_size
        out_w, out_h = result.image.size
        size_part = f"{width} x {height}"
        if (out_w, out_h) != (width, height):
            size_part += f" -> {out_w} x {out_h}"
        saving = (
            100 - (len(result.png) * 100 / result.raw_bytes)
            if result.raw_bytes
            else 0
        )
        parts = [
            size_part,
            f"{imageops.human_size(result.raw_bytes)} raw -> "
            f"{imageops.human_size(len(result.png))} on the clipboard "
            f"({saving:.0f}% smaller)",
        ]
        if latest_path is not None:
            parts.append(f"saved to {latest_path}")
        if notes:
            parts.append("; ".join(notes))
        return "   |   ".join(parts)

    def _copy_again(self) -> None:
        if not self._last_png or self._last_image is None:
            return
        clipboard.copy(
            self._last_png,
            self._last_image,
            include_dib=self.cfg["clipboard_dib_fallback"],
        )

    # -- settings ----------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        new_cfg = dialog.values()
        hotkey_changed = new_cfg["hotkey"] != self.cfg["hotkey"]
        self.cfg = new_cfg
        try:
            config.save(self.cfg)
            self.cfg = config.load()
        except OSError as exc:
            self._warn(f"Settings could not be written: {exc}")
        if hotkey_changed:
            self._register_hotkey()
        self._refresh_menu_text()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(None, "ShadowSnip", message)

    def quit(self) -> None:
        self.hotkeys.unregister()
        self.tray.hide()
        self.qapp.quit()


def build_icon(size: int = 64) -> QIcon:
    """Draw the tray icon so the app ships without any image assets."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(24, 24, 28))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 10, 10)

    marquee = QPen(QColor(235, 235, 240))
    marquee.setWidth(max(2, size // 16))
    marquee.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(marquee)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = size // 5
    painter.drawRect(inset, inset, size - inset * 2, size - inset * 2)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 99, 196))
    dot = size // 5
    painter.drawEllipse(size - inset - dot // 2, size - inset - dot // 2, dot, dot)
    painter.end()
    return QIcon(pixmap)
