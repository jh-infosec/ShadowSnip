"""Settings window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import platforms
import skins
import config as config_mod
import hotkey as hotkey_mod

# Long enough to alt-tab or click into another window without hurrying,
# short enough that nobody wonders whether the button worked.
PICK_SECONDS = 5

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
    # The skin picked in the list, as you pick it, before Save: so the window
    # can show it straight away. Cancel puts the old one back (app.py).
    skin_changed = Signal(str)

    # Width of the skin preview picture on the Appearance tab.
    SKIN_PREVIEW_WIDTH = 340

    def __init__(self, cfg: dict, parent=None, skin_preview=None):
        """`skin_preview(name)` returns a picture of the window in that skin, or None."""
        super().__init__(parent)
        self._skin_preview = skin_preview
        self.setWindowTitle("ShadowSnip settings")
        self.setMinimumWidth(460)
        self._cfg = dict(cfg)

        self.hotkey_edit = HotkeyEdit(cfg["hotkey"])
        self.note_hotkey_edit = HotkeyEdit(cfg["note_hotkey"])
        self.output_hotkey_edit = HotkeyEdit(cfg["output_hotkey"])

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

        self.quantize_ceiling = QSpinBox()
        self.quantize_ceiling.setRange(0, 16777216)
        self.quantize_ceiling.setSingleStep(1024)
        self.quantize_ceiling.setSpecialValueText("Never skip")
        self.quantize_ceiling.setValue(cfg["quantize_max_source_colors"])

        self.quantize_saving = QSpinBox()
        self.quantize_saving.setRange(0, 90)
        self.quantize_saving.setSuffix(" %")
        self.quantize_saving.setValue(cfg["quantize_min_saving"])

        for widget in (self.quantize_ceiling, self.quantize_saving):
            self.quantize_check.toggled.connect(widget.setEnabled)
            widget.setEnabled(cfg["quantize"])

        self.png_level = QSpinBox()
        self.png_level.setRange(0, 9)
        self.png_level.setValue(cfg["png_compress_level"])

        self.dib_check = QCheckBox("Also copy a plain bitmap for older programs")
        self.dib_check.setChecked(cfg["clipboard_dib_fallback"])

        self.auto_copy_check = QCheckBox(
            "Copy highlighted text as soon as the drag ends"
        )
        self.auto_copy_check.setChecked(cfg["auto_copy"])
        self.auto_copy_skip = QCheckBox(
            "Skip consoles, Explorer, the desktop, and VM/RDP/SSH windows"
        )
        self.auto_copy_skip.setChecked(cfg["auto_copy_skip_consoles"])
        self.auto_copy_double = QCheckBox(
            "Also copy on double-click (word) and triple-click (line)"
        )
        self.auto_copy_double.setChecked(cfg["auto_copy_double_click"])
        self.auto_copy_dedupe = QCheckBox(
            "Ignore a clip identical to the one before it"
        )
        self.auto_copy_dedupe.setChecked(cfg["auto_copy_dedupe"])
        self.auto_copy_toast = QCheckBox(
            "Show a confirmation near the cursor"
        )
        self.auto_copy_toast.setChecked(cfg["auto_copy_toast"])
        self.auto_copy_drag = QSpinBox()
        self.auto_copy_drag.setRange(1, 200)
        self.auto_copy_drag.setSuffix(" px")
        self.auto_copy_drag.setValue(cfg["auto_copy_min_drag"])
        self.auto_copy_blocked = QLineEdit(
            ", ".join(cfg["auto_copy_extra_blocked"])
        )
        self.auto_copy_blocked.setPlaceholderText(
            (
                "myvault, othertool - password managers are already covered"
                if platforms.IS_LINUX
                else "myvault.exe, othertool.exe - password managers are already covered"
            )
        )
        # Two ways in, because knowing a program's executable name is not
        # something anyone should have to look up. The first button covers the
        # usual case -- you were just in the program that misbehaved -- and the
        # countdown covers the rest, including programs reached from the tray
        # menu after alt-tabbing somewhere else.
        self.blocked_last = QPushButton("Block the app I was just in")
        self.blocked_last.clicked.connect(self._block_last_app)
        self.blocked_pick = QPushButton(f"Pick an app ({PICK_SECONDS}s)")
        self.blocked_pick.clicked.connect(self._pick_app)
        self.blocked_hint = QLabel("")
        self.blocked_hint.setWordWrap(True)
        self._pick_left = 0
        self._pick_timer = QTimer(self)
        self._pick_timer.setInterval(1000)
        self._pick_timer.timeout.connect(self._pick_tick)

        blocked_buttons = QHBoxLayout()
        blocked_buttons.setContentsMargins(0, 0, 0, 0)
        blocked_buttons.addWidget(self.blocked_last)
        blocked_buttons.addWidget(self.blocked_pick)
        blocked_buttons.addStretch(1)
        blocked_box = QWidget()
        blocked_layout = QVBoxLayout(blocked_box)
        blocked_layout.setContentsMargins(0, 0, 0, 0)
        blocked_layout.addWidget(self.auto_copy_blocked)
        blocked_layout.addLayout(blocked_buttons)
        blocked_layout.addWidget(self.blocked_hint)
        # Deliberately never disabled. These were greyed out while copy on
        # select was off, which meant the exclusion list -- the one setting you
        # reach for *because* the feature is misbehaving -- could not be filled
        # in until you had switched the misbehaving feature back on. Configuring
        # something before enabling it is normal, and none of these do anything
        # while `auto_copy` is off, so there is nothing to protect against.

        self.preview_check = QCheckBox("Show the preview window after a snip")
        self.preview_check.setChecked(cfg["show_preview"])

        self.dim = QSpinBox()
        self.dim.setRange(0, 255)
        self.dim.setValue(cfg["dim_opacity"])

        self.lab_root_edit = QLineEdit(cfg["lab_root"])
        self.lab_root_edit.setPlaceholderText("Default: a 'labs' folder inside the save folder")
        lab_browse = QPushButton("Browse...")
        lab_browse.clicked.connect(self._pick_lab_root)
        lab_row = QWidget()
        lab_layout = QHBoxLayout(lab_row)
        lab_layout.setContentsMargins(0, 0, 0, 0)
        lab_layout.addWidget(self.lab_root_edit, 1)
        lab_layout.addWidget(lab_browse)

        self.lab_index_check = QCheckBox(
            "Keep a lab record and lab.md index (needed for sections and notes)"
        )
        self.lab_index_check.setChecked(cfg["lab_index"])
        self.lab_caption_check = QCheckBox("Offer a caption box after each snip in a lab")
        self.lab_caption_check.setChecked(cfg["lab_caption"])
        self.lab_caption_check.setEnabled(cfg["lab_index"])
        self.lab_index_check.toggled.connect(self.lab_caption_check.setEnabled)
        self.lab_methodology_check = QCheckBox(
            "Start new labs with the methodology sections"
        )
        self.lab_methodology_check.setToolTip(
            "Recon, Enumeration, Initial access, Privilege escalation and "
            "Post-exploitation, laid out as sections when a new lab starts"
        )
        self.lab_methodology_check.setChecked(cfg["lab_methodology"])
        self.lab_methodology_check.setEnabled(cfg["lab_index"])
        self.lab_index_check.toggled.connect(self.lab_methodology_check.setEnabled)

        # The skin: a list to pick from, and a button that steps through them.
        self.skin_combo = QComboBox()
        for name in skins.NAMES:
            self.skin_combo.addItem(skins.LABELS[name], name)
            self.skin_combo.setItemData(
                self.skin_combo.count() - 1, skins.DESCRIPTIONS[name], Qt.ItemDataRole.ToolTipRole
            )
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(skins.normalise(cfg.get("skin")))))
        self.skin_next = QPushButton("Next")
        self.skin_next.setToolTip("Step to the next skin")
        self.skin_next.clicked.connect(self._next_skin)
        self.skin_about = QLabel()
        self.skin_about.setObjectName("SkinAbout")
        self.skin_about.setWordWrap(True)
        self.skin_combo.currentIndexChanged.connect(self._describe_skin)
        self._describe_skin()
        # The window itself, in the skin picked, updated as you cycle.
        self.skin_picture = QLabel()
        self.skin_picture.setObjectName("SkinPicture")
        self.skin_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.skin_picture.setVisible(skin_preview is not None)
        self.skin_combo.currentIndexChanged.connect(self._on_skin_picked)
        skin_row = QWidget()
        skin_layout = QHBoxLayout(skin_row)
        skin_layout.setContentsMargins(0, 0, 0, 0)
        skin_layout.addWidget(self.skin_combo, 1)
        skin_layout.addWidget(self.skin_next)

        # Five short tabs rather than one long column: the column had grown
        # taller than a laptop screen, and Save was below the bottom edge.
        self.tabs = QTabWidget()

        appearance = self._tab("Appearance")
        appearance.addRow("Skin", skin_row)
        appearance.addRow("", self.skin_about)
        appearance.addRow("", self.skin_picture)
        appearance.addRow(self.preview_check)
        appearance.addRow("Overlay dimming", self.dim)

        snipping = self._tab("Snipping")
        snipping.addRow("Snip hotkey", self.hotkey_edit)
        snipping.addRow("Quick note hotkey", self.note_hotkey_edit)
        snipping.addRow("Command output hotkey", self.output_hotkey_edit)
        snipping.addRow("Save folder", folder_row)
        snipping.addRow("Replaced file name", self.name_edit)
        snipping.addRow(self.history_check)
        snipping.addRow("Keep at most", self.history_limit)

        image = self._tab("Image")
        image.addRow("File format", self.format_combo)
        image.addRow("Lossy quality", self.quality)
        image.addRow("Longest edge", self.max_dimension)
        image.addRow(self.quantize_check)
        image.addRow("Colours", self.quantize_colors)
        image.addRow("Skip above", self.quantize_ceiling)
        image.addRow("Only if it saves", self.quantize_saving)
        image.addRow("PNG effort", self.png_level)
        image.addRow(self.dib_check)
        note = QLabel(
            "The clipboard always receives a compressed PNG. The file format "
            "setting applies to what is written to disk. Palette reduction is "
            "the only lossy step: it is skipped once a grab holds more "
            "distinct colours than the limit above, which keeps small text on "
            "code and terminal screenshots sharp at the cost of a larger file."
        )
        note.setWordWrap(True)
        image.addRow(note)

        copying = self._tab("Copy on select")
        copying.addRow(self.auto_copy_check)
        copying.addRow(self.auto_copy_double)
        copying.addRow(self.auto_copy_skip)
        copying.addRow(self.auto_copy_dedupe)
        copying.addRow(self.auto_copy_toast)
        copying.addRow("Shortest drag that counts", self.auto_copy_drag)
        copying.addRow("Never copy from", blocked_box)

        labs = self._tab("Labs")
        labs.addRow("Labs folder", lab_row)
        labs.addRow(self.lab_index_check)
        labs.addRow(self.lab_caption_check)
        labs.addRow(self.lab_methodology_check)

        # Outside the tabs, so they are always on screen whichever tab is open.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

        self._sync_quality()
        self._show_skin_picture(self.skin_combo.currentData() or "original")

    def _tab(self, title: str) -> QFormLayout:
        """A tab holding a form, inside a scroll area in case a screen is very small."""
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return form

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        """Never taller or wider than the screen it opens on, so Save is always visible."""
        screen = self.screen() or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        max_w, max_h = int(area.width() * 0.9), int(area.height() * 0.85)
        self.setMaximumHeight(max_h)
        width = min(max(self.width(), self.sizeHint().width()), max_w)
        height = min(max(self.height(), self._tallest_tab_height()), max_h)
        self.resize(width, height)
        frame = self.frameGeometry()
        if not area.contains(frame):
            frame.moveCenter(area.center())
            self.move(frame.topLeft())

    def _tallest_tab_height(self) -> int:
        """Dialog height that shows the longest tab without scrolling."""
        current = self.tabs.currentWidget()
        if current is None or not current.isVisible():
            return self.sizeHint().height()
        width = current.viewport().width()
        page_h = 0
        for i in range(self.tabs.count()):
            layout = self.tabs.widget(i).widget().layout()
            if layout.hasHeightForWidth():
                page_h = max(page_h, layout.totalHeightForWidth(width))
            else:
                page_h = max(page_h, layout.totalSizeHint().height())
        # A few pixels of slack: an exact fit still shows a scroll bar.
        return self.height() + max(0, page_h + 6 - current.viewport().height())

    def _sync_quality(self) -> None:
        self.quality.setEnabled(self.format_combo.currentData() != "png")

    # -- filling in the exclusion list -------------------------------------
    def _block_last_app(self) -> None:
        self._add_blocked(
            platforms.last_other_process(),
            "No other program's window could be found to name. Use "
            f"Pick an app ({PICK_SECONDS}s), or type the "
            f"{'process' if platforms.IS_LINUX else 'executable'} name.",
        )

    def _pick_app(self) -> None:
        """Give the user a few seconds to click into the program they mean."""
        self._pick_left = PICK_SECONDS
        self.blocked_pick.setEnabled(False)
        self._show_countdown()
        self._pick_timer.start()

    def _show_countdown(self) -> None:
        self.blocked_hint.setText(
            f"Click into the program you want excluded... {self._pick_left}"
        )

    def _pick_tick(self) -> None:
        self._pick_left -= 1
        if self._pick_left > 0:
            self._show_countdown()
            return
        self._pick_timer.stop()
        self.blocked_pick.setEnabled(True)
        self._add_blocked(
            platforms.foreground_process(),
            "Nothing but ShadowSnip was in front when the countdown ended, "
            "so nothing was added.",
        )

    def _add_blocked(self, name: str | None, failure: str) -> None:
        """Put `name` in the field, and say what happened either way.

        Silence would be indistinguishable from a broken button, and the two
        outcomes worth telling apart are 'added it' and 'it was already
        there' -- both of which look like nothing changing.
        """
        if not name:
            self.blocked_hint.setText(failure)
            return
        before = self.auto_copy_blocked.text()
        after = config_mod.add_name(before, name)
        self.auto_copy_blocked.setText(after)
        added = len(config_mod.normalise_names(after)) > len(
            config_mod.normalise_names(before)
        )
        self.blocked_hint.setText(
            f"Added {name}." if added else f"{name} is already on the list."
        )

    def _pick_lab_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the labs folder", self.lab_root_edit.text()
        )
        if folder:
            self.lab_root_edit.setText(folder)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the save folder", self.folder_edit.text()
        )
        if folder:
            self.folder_edit.setText(folder)

    def values(self) -> dict:
        cfg = dict(self._cfg)
        cfg["hotkey"] = self.hotkey_edit.spec
        cfg["note_hotkey"] = self.note_hotkey_edit.spec
        cfg["output_hotkey"] = self.output_hotkey_edit.spec
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
        cfg["quantize_max_source_colors"] = self.quantize_ceiling.value()
        cfg["quantize_min_saving"] = self.quantize_saving.value()
        cfg["png_compress_level"] = self.png_level.value()
        cfg["clipboard_dib_fallback"] = self.dib_check.isChecked()
        cfg["auto_copy"] = self.auto_copy_check.isChecked()
        cfg["auto_copy_skip_consoles"] = self.auto_copy_skip.isChecked()
        cfg["auto_copy_double_click"] = self.auto_copy_double.isChecked()
        cfg["auto_copy_dedupe"] = self.auto_copy_dedupe.isChecked()
        cfg["auto_copy_toast"] = self.auto_copy_toast.isChecked()
        cfg["auto_copy_min_drag"] = self.auto_copy_drag.value()
        # Normalised here rather than left for config.save, so the dict handed
        # back is already in its final shape even if the write then fails.
        cfg["auto_copy_extra_blocked"] = config_mod.normalise_names(
            self.auto_copy_blocked.text()
        )
        cfg["show_preview"] = self.preview_check.isChecked()
        cfg["dim_opacity"] = self.dim.value()
        cfg["lab_root"] = self.lab_root_edit.text().strip()
        cfg["lab_index"] = self.lab_index_check.isChecked()
        cfg["lab_caption"] = self.lab_caption_check.isChecked()
        cfg["lab_methodology"] = self.lab_methodology_check.isChecked()
        cfg["skin"] = self.skin_combo.currentData() or "original"
        return cfg

    # -- skin -----------------------------------------------------------------
    def _next_skin(self) -> None:
        self.skin_combo.setCurrentIndex((self.skin_combo.currentIndex() + 1) % self.skin_combo.count())

    def _describe_skin(self, *_args) -> None:
        name = self.skin_combo.currentData() or "original"
        self.skin_about.setText(skins.DESCRIPTIONS.get(name, ""))

    def _on_skin_picked(self, *_args) -> None:
        name = self.skin_combo.currentData() or "original"
        self.skin_changed.emit(name)
        self._show_skin_picture(name)

    def _show_skin_picture(self, name: str) -> None:
        if self._skin_preview is None:
            return
        try:
            picture = self._skin_preview(name)
        except Exception:  # noqa: BLE001 - a preview is never worth an error box
            picture = None
        if picture is None or picture.isNull():
            self.skin_picture.clear()
            return
        width = self.SKIN_PREVIEW_WIDTH
        ratio = self.devicePixelRatioF() or 1.0
        scaled = picture.scaledToWidth(
            int(width * ratio), Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(ratio)
        self.skin_picture.setPixmap(scaled)
