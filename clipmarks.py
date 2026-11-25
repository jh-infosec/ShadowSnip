"""Marks on a video clip (0.19.0): arrows, labels, boxes and blur, drawn once, on every frame.

Mark up (beside Trim under a clip) opens one frame of the clip with the same
tools as a snip: shapes, labels, numbered steps, callouts, the pen and
highlighter, spotlight, magnify and Redact. Save marks writes the clip again
with them on every frame, for the whole clip or from the moment chosen on.

The marks are an AnnotationDoc drawn on that frame. Each frame of the clip
becomes the doc's original in turn and is rendered with the same marks, so
a blur or a redaction blurs what is under it in that frame, not a frozen
copy of the first, and a spotlight dims each frame around the same place.

Crop, Text, the colour picker, Quick redact and the evidence stamp are not
offered: a crop would change the clip's size, and the others read or
describe one picture rather than mark the clip.

Like a trim, the clip as recorded is kept beside it, so As recorded (the
button that was Undo trim) takes the marks off again. A clip with sound loses the
sound, as a trimmed one does.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

import skins
from annotate import AnnotationDoc, AnnotCanvas, AnnotToolbar

# Tools that do not make sense on a clip; see the module notes.
LEFT_OUT = ("crop", "text", "picker")

STYLE = """
QDialog { background: #1c1c1f; color: #e6e6e6; }
QLabel { color: #c8c8cc; }
QLabel#MarkHint { color: #9aa3ad; }
QPushButton#Primary { background: #1273da; color: white; border: 1px solid #1273da;
                      border-radius: 4px; padding: 4px 14px; }
QPushButton#Primary:disabled { background: #3a3a40; color: #8a8a90; border-color: #3a3a40; }
"""


def has_marks(doc: AnnotationDoc | None) -> bool:
    """Whether anything visible has been drawn (marks, strokes or redactions not erased)."""
    if doc is None:
        return False
    from annotate import Mark, Redact, Stroke

    gone = doc.erased()
    return any(isinstance(op, (Mark, Stroke, Redact)) and op.id not in gone for op in doc.ops)


def overlay(doc: AnnotationDoc, from_ms: int = 0):
    """A `transform(image, at_ms)` for cliptrim: the marks on frames at or after `from_ms`."""
    from_ms = max(0, int(from_ms))

    def transform(image: QImage, at_ms: int) -> QImage:
        if at_ms < from_ms:
            return image
        frame = doc.clone()
        base = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if base.size() != doc.base.size():
            base = base.scaled(doc.base.size())
        frame.base = base
        return frame.render_full()

    return transform


class ClipMarkupDialog(QDialog):
    """One frame of the clip with the mark-up tools, and when the marks show."""

    def __init__(self, frame: QImage, at_ms: int, length_text: str, at_text: str,
                 prefs: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ShadowSnip - mark up the clip")
        self.setStyleSheet(skins.style(STYLE))
        self.resize(980, 680)
        self.at_ms = max(0, int(at_ms))

        self.canvas = AnnotCanvas()
        self.canvas.offer_save_as = False
        self.canvas.offer_copy_as = False
        self.tools = AnnotToolbar()
        if prefs:
            self.tools.set_prefs(prefs)
        self.canvas.prefs = dict(self.tools.prefs)
        for kind in LEFT_OUT:
            if kind in self.tools.buttons:
                self.tools.buttons[kind].hide()
        self.tools.btn_quick.hide()
        self.tools.btn_stamp.hide()
        self.tools.hints = {None: "Left-click a tool to pick it up, right-click for its options. "
                                  "Nothing changes until Save marks."}
        self.tools.tool_changed.connect(self.canvas.set_tool)
        self.tools.undo_requested.connect(self.canvas.undo)
        self.tools.redo_requested.connect(self.canvas.redo)
        self.tools.prefs_changed.connect(self._on_prefs)
        self.canvas.undo_changed.connect(self.tools.set_undo_enabled)
        self.canvas.redo_changed.connect(self.tools.set_redo_enabled)
        self.canvas.undo_changed.connect(self._sync)
        self.canvas.edited.connect(self._sync)
        self.canvas.load(frame)
        self.tools.set_available(True)
        self.tools.select(None)

        self.when = QComboBox()
        self.when.addItem(f"For the whole clip ({length_text})", 0)
        if self.at_ms > 0:
            self.when.addItem(f"From {at_text} to the end", self.at_ms)
        self.when.setToolTip("Play or drag to a moment before Mark up to start the marks there")
        hint = QLabel("Drawn on every frame. The clip as recorded is kept: As recorded takes the marks off.")
        hint.setObjectName("MarkHint")
        hint.setWordWrap(True)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Save marks")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(QLabel("Show the marks"))
        row.addWidget(self.when)
        row.addWidget(hint, 1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.tools)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(row)
        self._sync()

    def _on_prefs(self, prefs: dict) -> None:
        before = dict(self.canvas.prefs)
        self.canvas.prefs = dict(prefs)
        self.canvas.restyle_selected(before, prefs)

    def _sync(self, *_args) -> None:
        if hasattr(self, "btn_save"):   # loading the frame signals before the buttons exist
            self.btn_save.setEnabled(self.has_marks())

    def has_marks(self) -> bool:
        return has_marks(self.canvas.doc)

    def from_ms(self) -> int:
        return int(self.when.currentData() or 0)

    def transform(self):
        return overlay(self.canvas.doc, self.from_ms())

    def keyPressEvent(self, event):
        # Esc puts a tool down first, as in the main window; with none in hand it cancels.
        if event.key() == Qt.Key.Key_Escape and self.canvas.tool:
            self.tools.select(None)
            return
        super().keyPressEvent(event)
