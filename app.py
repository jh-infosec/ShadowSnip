"""Tray application and the snip pipeline.

Pipeline for one snip:

    freeze screens -> overlay -> crop -> compress -> clipboard -> disk -> preview

The clipboard and disk writes both happen automatically. Everything in the
preview window afterwards is optional.

When a lab is engaged the same snip also lands in that lab's folder, numbered
in capture order. Nothing else about the pipeline changes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRect, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

import capture
import clipboard
import config
import hotkey as hotkey_mod
import imageops
import lab
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
        self._last_disk: tuple[bytes, str] | None = None

        self.preview = PreviewWindow()
        self.preview.new_snip_requested.connect(self.request_snip)
        self.preview.lab_toggle_requested.connect(self.toggle_lab)

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

        self.action_folder = QAction("Open save folder", self)
        self.action_folder.triggered.connect(self._open_save_folder)
        menu.addAction(self.action_folder)

        menu.addSeparator()
        self.action_lab = QAction("Start lab...", self)
        self.action_lab.triggered.connect(self.toggle_lab)
        menu.addAction(self.action_lab)

        self.labs_menu = QMenu("Open a lab", menu)
        self.labs_menu.aboutToShow.connect(self._fill_labs_menu)
        menu.addMenu(self.labs_menu)

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

        name = lab.active_name(self.cfg)
        if name:
            self.action_lab.setText(f"Stop lab ({name})")
            self.action_folder.setText("Open lab folder")
            self.tray.setToolTip(
                f"ShadowSnip - lab: {name} ({lab.count(self.cfg)} snips)"
            )
        else:
            self.action_lab.setText("Start lab...")
            self.action_folder.setText("Open save folder")
            self.tray.setToolTip(f"ShadowSnip - press {label} to snip")
        self.tray.setIcon(build_icon(active=bool(name)))
        self.preview.set_lab_name(name)

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.request_snip()

    def _open_save_folder(self) -> None:
        target = lab.active_folder(self.cfg)
        if target is not None:
            storage.open_folder(target)
            return
        folder = storage.save_dir(self.cfg)
        storage.reveal(folder / f"{self.cfg['latest_name']}.{self.cfg['disk_format']}")

    # -- labs --------------------------------------------------------------
    def toggle_lab(self) -> None:
        if lab.is_active(self.cfg):
            self.stop_lab()
        else:
            self.start_lab()

    def start_lab(self) -> None:
        """Ask for a name, then send every following snip to that folder.

        An existing name resumes that lab and carries on numbering from where
        it stopped, which doubles as crash recovery.
        """
        parent = self.preview if self.preview.isVisible() else None
        name, ok = QInputDialog.getText(
            parent, "Start lab", "Lab name:", text=lab.active_name(self.cfg)
        )
        if not ok or not name.strip():
            return
        try:
            folder = lab.start(self.cfg, name)
        except lab.LabError as exc:
            self._warn(str(exc))
            return

        self.cfg["active_lab"] = name.strip()
        self._persist()
        self._refresh_menu_text()

        existing = lab.count(self.cfg)
        state = f"resumed, {existing} snips already in it" if existing else "new lab"

        # Starting a lab while looking at a snip means that snip belongs in it.
        if self.preview.isVisible() and self._last_disk is not None:
            self._file_current_snip_into_lab()

        self.tray.showMessage(
            "ShadowSnip",
            f"Lab '{self.cfg['active_lab']}' engaged ({state})\n{folder}",
            build_icon(active=True),
            4000,
        )

    def _file_current_snip_into_lab(self) -> None:
        data, ext = self._last_disk
        try:
            lab_path = lab.save(data, ext, self.cfg)
        except OSError as exc:
            self.preview.set_status(f"Could not write into the lab: {exc}")
            return
        if lab_path is None:
            return
        caption_cb = None
        if self.cfg["lab_index"] and self.cfg["lab_caption"]:
            caption_cb = self._caption_setter(lab_path.name)
        self.preview.attach_lab(lab_path.parent, caption_cb)
        self.preview.set_status(
            f"Lab {lab.active_name(self.cfg)} started; this snip filed as "
            f"{lab_path.name}"
        )

    def stop_lab(self) -> None:
        name = lab.active_name(self.cfg)
        total = lab.count(self.cfg)
        lab.stop(self.cfg)
        self._persist()
        self._refresh_menu_text()
        self.preview.attach_lab(None, None)
        if name:
            self.tray.showMessage(
                "ShadowSnip",
                f"Lab '{name}' closed with {total} snips. Snips go back to the "
                "normal save folder.",
                build_icon(),
                3000,
            )

    def _fill_labs_menu(self) -> None:
        """Rebuilt each time it opens, so new labs appear without a restart."""
        self.labs_menu.clear()
        names = lab.recent(self.cfg)
        if not names:
            empty = self.labs_menu.addAction("No labs yet")
            empty.setEnabled(False)
            return
        for name in names:
            action = self.labs_menu.addAction(name)
            action.triggered.connect(
                lambda _checked=False, n=name: storage.open_folder(
                    lab.folder(self.cfg, n)
                )
            )

    def _persist(self) -> None:
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._warn(f"Settings could not be written: {exc}")

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
        self._last_disk = (result.disk.data, result.disk.ext)

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
        lab_path: Path | None = None
        try:
            latest_path = storage.save_latest(
                result.disk.data, result.disk.ext, self.cfg
            )
            if lab.is_active(self.cfg):
                # The lab folder is the history for as long as it is engaged,
                # so the same snip does not land in three places at once.
                lab_path = lab.save(result.disk.data, result.disk.ext, self.cfg)
            else:
                storage.save_history(result.disk.data, result.disk.ext, self.cfg)
        except OSError as exc:
            notes.append(f"could not write to the save folder ({exc})")

        caption_cb = None
        if lab_path is not None and self.cfg["lab_index"] and self.cfg["lab_caption"]:
            caption_cb = self._caption_setter(lab_path.name)

        status = self._status_line(result, latest_path, lab_path, notes)
        if self.cfg["show_preview"]:
            self.preview.show_snip(
                image=image,
                disk_bytes=result.disk.data,
                ext=result.disk.ext,
                latest_path=latest_path,
                status=status,
                copy_again=self._copy_again,
                folder_path=lab_path.parent if lab_path else None,
                caption_cb=caption_cb,
            )
        else:
            self.tray.showMessage(
                "ShadowSnip", status, build_icon(active=lab_path is not None), 3000
            )

        if lab_path is not None:
            self._refresh_menu_text()

    def _caption_setter(self, filename: str):
        def apply(text: str) -> bool:
            return lab.set_caption(self.cfg, filename, text)

        return apply

    def _status_line(self, result, latest_path, lab_path, notes) -> str:
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
        if lab_path is not None:
            parts.append(f"lab {lab.active_name(self.cfg)}: {lab_path.name}")
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
        new_cfg["active_lab"] = self.cfg.get("active_lab", "")
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


def build_icon(size: int = 64, active: bool = False) -> QIcon:
    """Draw the tray icon so the app ships without any image assets.

    `active` adds a badge dot, so a lab that has been left engaged is visible
    at a glance instead of quietly collecting screenshots for three days.
    """
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

    if active:
        badge = size // 4
        painter.setBrush(QColor(46, 204, 113))
        painter.drawEllipse(size - badge - 3, 3, badge, badge)

    painter.end()
    return QIcon(pixmap)
