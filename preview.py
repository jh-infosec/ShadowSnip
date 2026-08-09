"""The window that appears after a snip.

The snip is already on the clipboard and already written to disk by the time
this opens, so every control here is optional: save a permanent copy, copy it
again, or take another snip.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import storage

STYLE = """
QWidget#Root { background: #1b1b1f; }
QLabel { color: #e6e6ec; }
QLabel#Status { color: #9a9aa6; font-size: 11px; }
QLabel#Canvas { background: #101013; border: 1px solid #2c2c33; }
QPushButton {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 6px 14px;
}
QPushButton:hover { background: #34343d; }
QPushButton:pressed { background: #232329; }
QPushButton#Primary { background: #0a63c4; border-color: #0a63c4; }
QPushButton#Primary:hover { background: #1273da; }
"""


class PreviewWindow(QWidget):
    new_snip_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._disk_bytes = b""
        self._disk_ext = "png"
        self._latest_path: Path | None = None
        self._copy_again = None

        self.setObjectName("Root")
        self.setWindowTitle("ShadowSnip")
        self.setStyleSheet(STYLE)
        self.resize(900, 640)

        self.canvas = QLabel()
        self.canvas.setObjectName("Canvas")
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(QSize(320, 200))

        self.status = QLabel()
        self.status.setObjectName("Status")

        self.btn_new = QPushButton("New snip")
        self.btn_new.setObjectName("Primary")
        self.btn_save = QPushButton("Save as...")
        self.btn_copy = QPushButton("Copy again")
        self.btn_folder = QPushButton("Open folder")
        self.btn_close = QPushButton("Close")

        self.btn_new.clicked.connect(self.new_snip_requested.emit)
        self.btn_save.clicked.connect(self.save_as)
        self.btn_copy.clicked.connect(self.copy_again)
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_close.clicked.connect(self.close)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_copy)
        bar.addWidget(self.btn_folder)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save_as)
        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy_again)
        QShortcut(QKeySequence("Esc"), self, self.close)

    # -- content -----------------------------------------------------------
    def show_snip(self, image: QImage, disk_bytes: bytes, ext: str,
                  latest_path: Path | None, status: str, copy_again) -> None:
        self._image = image
        self._disk_bytes = disk_bytes
        self._disk_ext = ext
        self._latest_path = latest_path
        self._copy_again = copy_again
        self.status.setText(status)
        self._render()
        self.show()
        self.raise_()
        self.activateWindow()

    def _render(self) -> None:
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image)
        area = self.canvas.size()
        if pixmap.width() > area.width() or pixmap.height() > area.height():
            pixmap = pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.canvas.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    # -- actions -----------------------------------------------------------
    def save_as(self) -> None:
        if not self._disk_bytes:
            return
        start = storage.suggested_name(self._disk_ext)
        if self._latest_path is not None:
            start = str(self._latest_path.parent / start)
        filters = "PNG image (*.png);;WebP image (*.webp);;JPEG image (*.jpg);;All files (*)"
        path, _ = QFileDialog.getSaveFileName(self, "Save snip", start, filters)
        if not path:
            return
        try:
            storage.write_atomic(Path(path), self._disk_bytes)
        except OSError as exc:
            QMessageBox.warning(self, "ShadowSnip", f"Could not write the file: {exc}")
            return
        self.status.setText(f"Saved to {path}")

    def copy_again(self) -> None:
        if self._copy_again is None:
            return
        try:
            self._copy_again()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.warning(self, "ShadowSnip", f"Could not copy: {exc}")
            return
        self.status.setText("Copied to the clipboard again")

    def open_folder(self) -> None:
        if self._latest_path is None:
            return
        try:
            storage.reveal(self._latest_path)
        except OSError as exc:
            QMessageBox.warning(self, "ShadowSnip", f"Could not open the folder: {exc}")

    def center_on_cursor_screen(self) -> None:
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())
