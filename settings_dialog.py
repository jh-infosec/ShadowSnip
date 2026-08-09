"""Settings window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import hotkey as hotkey_mod

_QT_KEY_NAMES = {
    Qt.Key.Key_Print: "prtsc",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Space: "space",
}
for _i in range(1, 25):
    _QT_KEY_NAMES[Qt.Key(Qt.Key.Key_F1 + _i - 1)] = f"f{_i}"


class HotkeyEdit(QLineEdit):
    """Click, then press the combination you want."""

    def __init__(self, spec: str, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click here, then press a key combination")
        self.spec = spec
        self.setText(hotkey_mod.describe(spec))

    def keyPressEvent(self, event):
        key = event.key()
        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_unknown,
        ):
            return

        mods = event.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")

        name = _QT_KEY_NAMES.get(Qt.Key(key))
        if name is None:
            text = event.text().strip()
            if text and (text.isalpha() or text.isdigit()):
                name = text.lower()
        if name is None:
            return

        parts.append(name)
        spec = "+".join(parts)
        try:
            hotkey_mod.parse(spec)
        except hotkey_mod.HotkeyError:
            return
        self.spec = spec
        self.setText(hotkey_mod.describe(spec))


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ShadowSnip settings")
        self.setMinimumWidth(460)
        self._cfg = dict(cfg)

        self.hotkey_edit = HotkeyEdit(cfg["hotkey"])

        self.folder_edit = QLineEdit(cfg["save_dir"])
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_folder)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(browse)

        self.name_edit = QLineEdit(cfg["latest_name"])

        self.history_check = QCheckBox("Keep a timestamped copy of every snip")
        self.history_check.setChecked(cfg["keep_history"])
        self.history_limit = QSpinBox()
        self.history_limit.setRange(1, 5000)
        self.history_limit.setValue(cfg["history_limit"])
        self.history_check.toggled.connect(self.history_limit.setEnabled)
        self.history_limit.setEnabled(cfg["keep_history"])

        self.format_combo = QComboBox()
        self.format_combo.addItem("PNG (lossless)", "png")
        self.format_combo.addItem("WebP (smaller, lossy)", "webp")
        self.format_combo.addItem("JPEG (smallest, lossy)", "jpeg")
        index = self.format_combo.findData(cfg["disk_format"])
        self.format_combo.setCurrentIndex(max(0, index))

        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(
            cfg["webp_quality"] if cfg["disk_format"] == "webp" else cfg["jpeg_quality"]
        )
        self.format_combo.currentIndexChanged.connect(self._sync_quality)

        self.max_dimension = QSpinBox()
        self.max_dimension.setRange(0, 30000)
        self.max_dimension.setSingleStep(100)
        self.max_dimension.setSpecialValueText("Full size")
        self.max_dimension.setSuffix(" px")
        self.max_dimension.setValue(cfg["max_dimension"])

        self.quantize_check = QCheckBox("Reduce the colour palette when it saves space")
        self.quantize_check.setChecked(cfg["quantize"])
        self.quantize_colors = QSpinBox()
        self.quantize_colors.setRange(2, 256)
        self.quantize_colors.setValue(cfg["quantize_colors"])
        self.quantize_check.toggled.connect(self.quantize_colors.setEnabled)
        self.quantize_colors.setEnabled(cfg["quantize"])

        self.png_level = QSpinBox()
        self.png_level.setRange(0, 9)
        self.png_level.setValue(cfg["png_compress_level"])

        self.dib_check = QCheckBox("Also copy a plain bitmap for older programs")
        self.dib_check.setChecked(cfg["clipboard_dib_fallback"])

        self.preview_check = QCheckBox("Show the preview window after a snip")
        self.preview_check.setChecked(cfg["show_preview"])

        self.dim = QSpinBox()
        self.dim.setRange(0, 255)
        self.dim.setValue(cfg["dim_opacity"])

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Snip hotkey", self.hotkey_edit)
        form.addRow("Save folder", folder_row)
        form.addRow("Replaced file name", self.name_edit)
        form.addRow(self.history_check)
        form.addRow("Keep at most", self.history_limit)
        form.addRow("File format", self.format_combo)
        form.addRow("Lossy quality", self.quality)
        form.addRow("Longest edge", self.max_dimension)
        form.addRow(self.quantize_check)
        form.addRow("Colours", self.quantize_colors)
        form.addRow("PNG effort", self.png_level)
        form.addRow(self.dib_check)
        form.addRow(self.preview_check)
        form.addRow("Overlay dimming", self.dim)

        note = QLabel(
            "The clipboard always receives a compressed PNG. The file format "
            "setting applies to what is written to disk."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

        self._sync_quality()

    def _sync_quality(self) -> None:
        self.quality.setEnabled(self.format_combo.currentData() != "png")

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the save folder", self.folder_edit.text()
        )
        if folder:
            self.folder_edit.setText(folder)

    def values(self) -> dict:
        cfg = dict(self._cfg)
        cfg["hotkey"] = self.hotkey_edit.spec
        cfg["save_dir"] = self.folder_edit.text().strip()
        cfg["latest_name"] = self.name_edit.text().strip()
        cfg["keep_history"] = self.history_check.isChecked()
        cfg["history_limit"] = self.history_limit.value()
        cfg["disk_format"] = self.format_combo.currentData()
        if cfg["disk_format"] == "webp":
            cfg["webp_quality"] = self.quality.value()
        elif cfg["disk_format"] == "jpeg":
            cfg["jpeg_quality"] = self.quality.value()
        cfg["max_dimension"] = self.max_dimension.value()
        cfg["quantize"] = self.quantize_check.isChecked()
        cfg["quantize_colors"] = self.quantize_colors.value()
        cfg["png_compress_level"] = self.png_level.value()
        cfg["clipboard_dib_fallback"] = self.dib_check.isChecked()
        cfg["show_preview"] = self.preview_check.isChecked()
        cfg["dim_opacity"] = self.dim.value()
        return cfg
