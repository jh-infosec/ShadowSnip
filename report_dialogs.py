"""The two report dialogs (0.9.0): a finding, and command output to file.

Both are plain Qt dialogs, like Settings. They only collect what was typed;
app.py does the filing through lab.py.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

import cvss
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
        self._build_cvss(existing.get("cvss", ""))

        form = QFormLayout()
        form.addRow("Section", where)
        form.addRow("Severity", self.severity)
        form.addRow("", self.use_cvss)
        form.addRow("", self.cvss_box)
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
        data["cvss"] = self.cvss_vector.text().strip() if self._cvss_ok() else ""
        return data

    # -- CVSS 3.1 (0.15.0) ---------------------------------------------------------
    def _build_cvss(self, vector: str) -> None:
        """A tick box, the vector as text, and a picker per base metric, kept in step.

        Paste a vector from a CVE or NVD, or build one with the pickers; the
        score and rating show as you go, and the severity follows the rating.
        """
        self._syncing = True   # the pickers fill in quietly while being built
        self.use_cvss = QCheckBox("Score it with CVSS 3.1")
        self.use_cvss.setToolTip("The severity then follows the CVSS rating, and reports show the score")
        self.cvss_vector = QLineEdit()
        self.cvss_vector.setPlaceholderText("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        self.cvss_vector.setFont(_mono())
        self.cvss_score = QLabel("")
        self.cvss_score.setObjectName("CvssScore")
        self.cvss_score.setMinimumWidth(self.cvss_score.fontMetrics().horizontalAdvance("10.0 Critical") + 12)
        self.cvss_combos: dict[str, QComboBox] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for index, (key, name, choices) in enumerate(cvss.METRICS):
            combo = QComboBox()
            for code, label in choices:
                combo.addItem(label, code)
            combo.setToolTip(f"{name} ({key})")
            combo.currentIndexChanged.connect(self._cvss_from_pickers)
            self.cvss_combos[key] = combo
            caption = QLabel(name)
            caption.setObjectName("FieldLabel")
            row, col = divmod(index, 4)
            grid.addWidget(caption, row * 2, col)
            grid.addWidget(combo, row * 2 + 1, col)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.cvss_vector, 1)
        top.addWidget(self.cvss_score)
        self.cvss_box = QWidget()
        box_layout = QVBoxLayout(self.cvss_box)
        box_layout.setContentsMargins(0, 0, 0, 4)
        box_layout.setSpacing(6)
        box_layout.addLayout(top)
        box_layout.addLayout(grid)

        self._syncing = False
        self.cvss_vector.textChanged.connect(self._cvss_from_text)
        self.use_cvss.toggled.connect(self._cvss_toggled)
        self.cvss_vector.setText(vector or "")
        if not vector:
            self._cvss_from_pickers()   # a starting vector, from the pickers' first values
        self.use_cvss.setChecked(bool(vector))
        self._cvss_toggled(bool(vector))

    def _cvss_ok(self) -> bool:
        if not self.use_cvss.isChecked():
            return False
        try:
            cvss.parse(self.cvss_vector.text())
        except cvss.CvssError:
            return False
        return True

    def _cvss_toggled(self, on: bool) -> None:
        self.cvss_box.setVisible(on)
        self.severity.setEnabled(not on)
        self.severity.setToolTip("Follows the CVSS rating while scoring is on" if on else "")
        if on:
            self._cvss_from_text(self.cvss_vector.text())
        self.adjustSize()

    def _cvss_from_pickers(self, *_args) -> None:
        if self._syncing:
            return
        metrics = {key: combo.currentData() for key, combo in self.cvss_combos.items()}
        version = "3.1"
        try:
            version = cvss.parse(self.cvss_vector.text())[0]
        except cvss.CvssError:
            pass
        self.cvss_vector.setText(cvss.vector_of(metrics, version))

    def _cvss_from_text(self, text: str) -> None:
        try:
            canonical, score, rating = cvss.score(text)
            _version, metrics = cvss.parse(text)
        except cvss.CvssError as exc:
            self.cvss_score.setText("Not scored")
            self.cvss_score.setToolTip(str(exc))
            self.cvss_score.setStyleSheet("color: #d6332e;")
            return
        self._syncing = True
        try:
            for key, combo in self.cvss_combos.items():
                combo.setCurrentIndex(max(0, combo.findData(metrics[key])))
        finally:
            self._syncing = False
        self.cvss_score.setText(f"{score:.1f} {rating}")
        self.cvss_score.setToolTip(canonical)
        self.cvss_score.setStyleSheet("")
        if self.use_cvss.isChecked():
            self.severity.setCurrentText(cvss.severity_for(score))


class ExportDialog(QDialog):
    """What to export (0.15.0): the format, and the whole lab or only its findings."""

    FORMATS = (
        ("html", "Web page (.html)", "One page with the images inside. Opens in any browser."),
        ("docx", "Word document (.docx)", "To edit, or paste into a client template."),
        ("pdf", "PDF (.pdf)", "Fixed pages with page numbers, ready to hand over."),
    )

    def __init__(self, fmt: str, scope: str, findings: int, docx_ok: bool = True, parent=None,
                 encrypted: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Export report")
        self.setMinimumWidth(460)

        heading = QLabel("Format")
        heading.setObjectName("FieldLabel")
        self.format_buttons: dict[str, QRadioButton] = {}
        # Two groups, so picking a format does not untick the scope.
        self._format_group = QButtonGroup(self)
        self._scope_group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        for key, label, hint in self.FORMATS:
            button = QRadioButton(label)
            button.setToolTip(hint)
            if key == "docx" and not docx_ok:
                button.setEnabled(False)
                button.setToolTip("Needs python-docx: pip install python-docx")
            self.format_buttons[key] = button
            self._format_group.addButton(button)
            layout.addWidget(button)
        chosen = fmt if fmt in self.format_buttons and self.format_buttons[fmt].isEnabled() else "html"
        self.format_buttons[chosen].setChecked(True)

        heading = QLabel("What goes in")
        heading.setObjectName("FieldLabel")
        layout.addSpacing(6)
        layout.addWidget(heading)
        self.scope_full = QRadioButton("The whole lab")
        self.scope_full.setToolTip("Everything in lab.md, in order, with the findings summary at the top")
        noun = "finding" if findings == 1 else "findings"
        self.scope_findings = QRadioButton(f"Findings only ({findings} {noun})")
        self.scope_findings.setToolTip(
            "Each finding with the snips, notes and output filed in its section, most severe "
            "first. Recon and anything not under a finding is left out.")
        self.scope_findings.setEnabled(findings > 0)
        self._scope_group.addButton(self.scope_full)
        self._scope_group.addButton(self.scope_findings)
        layout.addWidget(self.scope_full)
        layout.addWidget(self.scope_findings)
        if scope == "findings" and findings > 0:
            self.scope_findings.setChecked(True)
        else:
            self.scope_full.setChecked(True)
        if findings == 0:
            hint = QLabel("No findings yet: right-click a section in the Outline and choose Mark as finding.")
            hint.setWordWrap(True)
            hint.setObjectName("FieldLabel")
            layout.addWidget(hint)

        if encrypted:
            warning = QLabel("This lab is encrypted, but the export is not: it is a plain file for "
                             "handing over. Keep it somewhere safe.")
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #f0a020;")
            layout.addWidget(warning)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_export = buttons.addButton("Export...", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_export.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addSpacing(6)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        fmt = next(key for key, button in self.format_buttons.items() if button.isChecked())
        return fmt, "findings" if self.scope_findings.isChecked() else "full"


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
