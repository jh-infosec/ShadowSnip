"""The two report dialogs (0.9.0): a finding, and command output to file.

Both are plain Qt dialogs, like Settings. They only collect what was typed;
app.py does the filing through lab.py.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

import lab

# Result code for "Not a finding": remove the finding from the section.
REMOVE = 2

_HOSTISH = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}(:\d+)?|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+)$")
# A shell prompt at the start of pasted output: "$ cmd", "# cmd", or Kali's
# two-line prompt ending "└─$ cmd".
_PROMPT = re.compile(
    r"^\s*(?:"
    r"(?:.*[└╰]─+|[\w.-]+@[\w.-]+:\S*|\[[^\]]*\])?[$#]\s+"  # bash-style
    r"|PS [^>]*>\s*"  # PowerShell
    r"|[A-Za-z]:\\[^>]*>"  # cmd.exe
    r")(\S.*)$"
)


def guess_host(path: str) -> str:
    """The host a finding is about, when the breadcrumb starts with one."""
    for part in str(path or "").split(lab.SECTION_SEPARATOR):
        part = part.strip()
        if _HOSTISH.match(part):
            return part
    return ""


def split_command(text: str) -> tuple[str, str]:
    """Pasted terminal text as (command, output).

    When the first line is a prompt and a command, that line becomes the
    label and the rest the output. Otherwise there is no label.
    """
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    # Kali's prompt is two lines: "┌──(user㉿host)-[~]" then "└─$ command".
    start = 1 if lines and lines[0].lstrip().startswith(("\u250c", "\u256d")) else 0
    if len(lines) > start:
        match = _PROMPT.match(lines[start])
        if match:
            return match.group(1).strip(), "\n".join(lines[start + 1:])
    return "", "\n".join(lines)


def _mono() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class FindingDialog(QDialog):
    """Mark a section as a finding, or edit or remove one."""

    def __init__(self, path: str, existing: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Finding")
        self.setMinimumWidth(520)
        existing = existing or {}
        self.path = path

        where = QLabel(path.replace(lab.SECTION_SEPARATOR, " / "))
        where.setTextFormat(Qt.TextFormat.PlainText)
        where.setWordWrap(True)
        font = where.font()
        font.setBold(True)
        where.setFont(font)

        self.severity = QComboBox()
        self.severity.addItems(list(lab.SEVERITIES))
        self.severity.setCurrentText(existing.get("severity") or "Medium")
        self.host = QLineEdit(existing.get("host", "") or guess_host(path))
        self.host.setPlaceholderText("10.10.10.3, or a hostname or URL")

        self.fields: dict[str, QPlainTextEdit] = {}
        hints = {
            "description": "What the weakness is and where it was found",
            "impact": "What an attacker can do with it",
            "remediation": "How to fix it",
        }
        form = QFormLayout()
        form.addRow("Section", where)
        form.addRow("Severity", self.severity)
        form.addRow("Affected host", self.host)
        for field in lab.FINDING_FIELDS:
            box = QPlainTextEdit(existing.get(field, ""))
            box.setPlaceholderText(hints[field])
            box.setTabChangesFocus(True)
            box.setMinimumHeight(70)
            self.fields[field] = box
            form.addRow(field.capitalize(), box)

        note = QLabel(
            "The snips and notes filed in this section are the finding's "
            "evidence. lab.md shows the finding under the section's heading and "
            "in the findings summary at the top."
        )
        note.setWordWrap(True)
        note.setObjectName("FieldLabel")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.btn_remove = None
        if existing:
            self.btn_remove = QPushButton("Not a finding")
            self.btn_remove.setToolTip("Remove the finding; the section and its evidence stay")
            buttons.addButton(self.btn_remove, QDialogButtonBox.ButtonRole.DestructiveRole)
            self.btn_remove.clicked.connect(lambda: self.done(REMOVE))

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.fields["description"].setFocus()

    def values(self) -> dict:
        data = {"severity": self.severity.currentText(), "host": self.host.text()}
        for field, box in self.fields.items():
            data[field] = box.toPlainText()
        return data


class OutputDialog(QDialog):
    """Check command output, then file it as a code block."""

    def __init__(self, text: str, where: str, can_attach: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File command output")
        self.setMinimumSize(620, 420)
        command, output = split_command(text)

        self.command = QLineEdit(command)
        self.command.setPlaceholderText("The command that produced it (optional)")
        self.command.setFont(_mono())

        self.output = QPlainTextEdit(output)
        self.output.setFont(_mono())
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setPlaceholderText("Paste or type the output here")

        self.attach = QCheckBox("Attach to the snip on screen")
        self.attach.setVisible(can_attach)
        self._can_attach = bool(can_attach)
        self.attach.setToolTip("Show it directly under that snip in lab.md")

        hint = QLabel(
            f"Filed under {where} as a code block. Check it for passwords and "
            "tokens before filing: it goes into lab.md as text."
        )
        hint.setWordWrap(True)
        hint.setObjectName("FieldLabel")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_file = buttons.addButton("File it", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_file.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.output.textChanged.connect(self._sync)
        self._sync()

        form = QFormLayout()
        form.addRow("Command", self.command)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.output, 1)
        layout.addWidget(self.attach)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _sync(self) -> None:
        self.btn_file.setEnabled(bool(self.output.toPlainText().strip()))

    def values(self) -> tuple[str, str, bool]:
        """(command label, output, attach)."""
        return (self.command.text().strip(), self.output.toPlainText(),
                self._can_attach and self.attach.isChecked())
