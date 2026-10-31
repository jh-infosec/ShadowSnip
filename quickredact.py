"""The Quick redact window (0.10.0): what was found, and which kinds to hide.

ocr.find_sensitive() does the finding. This shows the result grouped by kind,
each with a tick box and the matches listed (partly masked, so the window
itself is not a second place a password is shown in full), and returns the
kinds to cover. The covering is done by the canvas, as ordinary redactions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

import ocr

# Matches listed per kind before "and N more".
LIST_LIMIT = 4


def masked(text: str) -> str:
    """Enough of a match to recognise it, never the whole secret."""
    text = str(text)
    if len(text) <= 4:
        return "*" * len(text)
    keep = 2 if len(text) < 12 else 4
    return f"{text[:keep]}{'*' * min(8, len(text) - keep * 2)}{text[-keep:]}"


class QuickRedactDialog(QDialog):
    def __init__(self, found, remembered=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick redact")
        self.setMinimumWidth(420)
        counts: dict[str, list[str]] = {}
        for item in found:
            counts.setdefault(item.kind, []).append(item.text)
        remembered = set(remembered or ()) if remembered is not None else None

        intro = QLabel(
            "Found in this snip. Tick what to hide; each is covered with a "
            "redaction you can erase on its own, and one undo takes them all back."
        )
        intro.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        self.checks: dict[str, QCheckBox] = {}
        for kind, (label, default_on) in ocr.KINDS.items():
            if kind not in counts:
                continue
            texts = counts[kind]
            box = QCheckBox(f"{label} ({len(texts)})")
            box.setChecked(kind in remembered if remembered is not None else default_on)
            self.checks[kind] = box
            shown = ", ".join(masked(t) for t in texts[:LIST_LIMIT])
            if len(texts) > LIST_LIMIT:
                shown += f", and {len(texts) - LIST_LIMIT} more"
            detail = QLabel(shown)
            detail.setObjectName("FieldLabel")
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setWordWrap(True)
            detail.setContentsMargins(24, 0, 0, 6)
            layout.addWidget(box)
            layout.addWidget(detail)

        note = QLabel(
            "Read from the picture, so check the result: an unusual font or a "
            "low-contrast screenshot can hide a match, and a redaction drawn by hand "
            "covers anything Quick redact missed."
        )
        note.setWordWrap(True)
        note.setObjectName("FieldLabel")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_hide = buttons.addButton("Hide them", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_hide.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for box in self.checks.values():
            box.toggled.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.btn_hide.setEnabled(any(box.isChecked() for box in self.checks.values()))

    def chosen_kinds(self) -> set[str]:
        return {kind for kind, box in self.checks.items() if box.isChecked()}
