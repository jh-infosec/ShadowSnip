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
    QStackedWidget,
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

    # -- CVSS 3.1 (0.15.0) and 4.0 (0.17.0) -------------------------------------------
    def _build_cvss(self, vector: str) -> None:
        """A tick box, a version, the vector as text, and a picker per base metric, kept in step.

        Paste a vector from a CVE or NVD, or build one with the pickers; the
        score and rating show as you go, and the severity follows the rating.
        Pasting a 4.0 vector switches the pickers to 4.0's eleven metrics.
        """
        self._syncing = True   # the pickers fill in quietly while being built
        self.use_cvss = QCheckBox("Score it with CVSS")
        self.use_cvss.setToolTip("The severity then follows the CVSS rating, and reports show the score")
        self.cvss_version = QComboBox()
        for version in cvss.VERSIONS:
            self.cvss_version.addItem(f"CVSS {version}", version)
        self.cvss_version.setToolTip("3.1 is what most exams and CVE records still use; 4.0 is the newer standard")
        self.cvss_version.currentIndexChanged.connect(self._cvss_version_picked)
        self.cvss_vector = QLineEdit()
        self.cvss_vector.setFont(_mono())
        self.cvss_score = QLabel("")
        self.cvss_score.setObjectName("CvssScore")
        self.cvss_score.setMinimumWidth(self.cvss_score.fontMetrics().horizontalAdvance("10.0 Critical") + 12)
        self.cvss_pickers: dict[str, dict[str, QComboBox]] = {}
        self.cvss_grids = QStackedWidget()
        for version in cvss.VERSIONS:
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(4)
            combos: dict[str, QComboBox] = {}
            columns = 4
            for index, (key, name, choices) in enumerate(cvss.metrics_for(version)):
                combo = QComboBox()
                for code, label in choices:
                    combo.addItem(label, code)
                combo.setToolTip(f"{name} ({key})")
                combo.currentIndexChanged.connect(self._cvss_from_pickers)
                combos[key] = combo
                caption = QLabel(name)
                caption.setObjectName("FieldLabel")
                row, col = divmod(index, columns)
                grid.addWidget(caption, row * 2, col)
                grid.addWidget(combo, row * 2 + 1, col)
            self.cvss_pickers[version] = combos
            self.cvss_grids.addWidget(page)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.cvss_version)
        top.addWidget(self.cvss_vector, 1)
        top.addWidget(self.cvss_score)
        self.cvss_box = QWidget()
        box_layout = QVBoxLayout(self.cvss_box)
        box_layout.setContentsMargins(0, 0, 0, 4)
        box_layout.setSpacing(6)
        box_layout.addLayout(top)
        box_layout.addWidget(self.cvss_grids)

        self._show_version(cvss.version_of(vector) or "3.1")
        self._syncing = False
        self.cvss_vector.textChanged.connect(self._cvss_from_text)
        self.use_cvss.toggled.connect(self._cvss_toggled)
        self.cvss_vector.setText(vector or "")
        if not vector:
            self._cvss_from_pickers()   # a starting vector, from the pickers' first values
        self.use_cvss.setChecked(bool(vector))
        self._cvss_toggled(bool(vector))

    @property
    def cvss_combos(self) -> dict[str, QComboBox]:
        """The pickers of the version showing."""
        return self.cvss_pickers[self._cvss_shown]

    def _show_version(self, version: str) -> None:
        version = "4.0" if version == "4.0" else "3.1"
        self._cvss_shown = version
        self.cvss_grids.setCurrentIndex(cvss.VERSIONS.index(version))
        was = self.cvss_version.blockSignals(True)
        self.cvss_version.setCurrentIndex(cvss.VERSIONS.index(version))
        self.cvss_version.blockSignals(was)
        self.cvss_vector.setPlaceholderText(
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N" if version == "4.0"
            else "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")

    def _cvss_version_picked(self, _index: int) -> None:
        """A different version chosen: start from its pickers (vectors do not translate)."""
        self._show_version(self.cvss_version.currentData())
        self._cvss_from_pickers(force=True)

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

    def _cvss_from_pickers(self, *_args, force: bool = False) -> None:
        if self._syncing:
            return
        version = self._cvss_shown
        metrics = {key: combo.currentData() for key, combo in self.cvss_combos.items()}
        try:
            text_version, current = cvss.parse(self.cvss_vector.text())
        except cvss.CvssError:
            text_version, current = "", {}
        if version == "4.0" and text_version == "4.0" and not force:
            # Keep threat, environmental and supplemental metrics a pasted vector had.
            metrics = {**current, **metrics}
        if version == "3.1" and text_version == "3.0" and not force:
            version = "3.0"
        self.cvss_vector.setText(cvss.vector_of(metrics, version))

    def _cvss_from_text(self, text: str) -> None:
        try:
            canonical, score, rating = cvss.score(text)
            version, metrics = cvss.parse(text)
        except cvss.CvssError as exc:
            self.cvss_score.setText("Not scored")
            self.cvss_score.setToolTip(str(exc))
            self.cvss_score.setStyleSheet("color: #d6332e;")
            return
        self._syncing = True
        try:
            self._show_version("4.0" if version == "4.0" else "3.1")
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
                 encrypted: bool = False, meta: dict | None = None, template: str = "",
                 lab_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Export report")
        self.setMinimumWidth(520)
        meta = dict(meta or {})
        self._lab_name = lab_name

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

        self._build_front_matter(layout, meta, template)
        for button in self.format_buttons.values():
            button.toggled.connect(self._sync_front_matter)
        self.scope_full.toggled.connect(self._sync_front_matter)
        self._sync_front_matter()

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

    # -- the front matter and the Word template (0.17.0) -----------------------------------
    def _build_front_matter(self, layout, meta: dict, template: str) -> None:
        heading = QLabel("Front pages")
        heading.setObjectName("FieldLabel")
        layout.addSpacing(6)
        layout.addWidget(heading)
        self.cover = QCheckBox("Cover page")
        self.cover.setToolTip("A first page with the title, who it is for and by, the date and the finding counts")
        self.cover.setChecked(bool(meta.get("cover")))
        self.toc = QCheckBox("Table of contents")
        self.toc.setToolTip("The sections with their page numbers (Word numbers them when it opens the file)")
        self.toc.setChecked(bool(meta.get("toc")))
        row = QHBoxLayout()
        row.addWidget(self.cover)
        row.addWidget(self.toc)
        row.addStretch(1)
        layout.addLayout(row)
        self.title = QLineEdit(meta.get("title", ""))
        self.client = QLineEdit(meta.get("client", ""))
        self.client.setPlaceholderText("The client, or Hack The Box, or OffSec")
        self.author = QLineEdit(meta.get("author", ""))
        self.author.setPlaceholderText("Your name, as it goes on the report")
        self.date = QLineEdit(meta.get("date", ""))
        import report

        self.date.setPlaceholderText(report.normalise_meta(None, "x")["date"] + " (today)")
        self.details = QWidget()
        form = QFormLayout(self.details)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Title", self.title)
        form.addRow("Prepared for", self.client)
        form.addRow("Prepared by", self.author)
        form.addRow("Date", self.date)
        layout.addWidget(self.details)

        self.template_path = template or ""
        self.template_label = QLabel("")
        self.template_label.setWordWrap(True)
        self.template_label.setObjectName("FieldLabel")
        self.btn_template = QPushButton("Choose...")
        self.btn_template.setToolTip(
            "A .docx or .dotx with your styles, logo, headers and cover. Write {{report}} where the "
            "report goes, and {{title}}, {{client}}, {{author}}, {{date}} or {{lab}} anywhere to have them filled in.")
        self.btn_template.clicked.connect(self._choose_template)
        self.btn_no_template = QPushButton("No template")
        self.btn_no_template.clicked.connect(lambda: self._set_template(""))
        self.template_row = QWidget()
        tpl = QHBoxLayout(self.template_row)
        tpl.setContentsMargins(0, 0, 0, 0)
        caption = QLabel("Word template")
        tpl.addWidget(caption)
        tpl.addWidget(self.template_label, 1)
        tpl.addWidget(self.btn_template)
        tpl.addWidget(self.btn_no_template)
        layout.addWidget(self.template_row)
        self.cover.toggled.connect(self._sync_front_matter)
        self.toc.toggled.connect(self._sync_front_matter)
        self._set_template(self.template_path)

    def _choose_template(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        start = str(Path(self.template_path).parent) if self.template_path else str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(self, "Word template", start, "Word templates (*.docx *.dotx)")
        if chosen:
            self._set_template(chosen)

    def _set_template(self, path: str) -> None:
        from pathlib import Path

        self.template_path = path or ""
        self.template_label.setText(Path(path).name if path else "None: ShadowSnip's own layout")
        self.template_label.setToolTip(path)
        self.btn_no_template.setEnabled(bool(path))
        self._sync_front_matter()

    def _sync_front_matter(self, *_args) -> None:
        if not hasattr(self, "template_row"):
            return
        import report

        fmt = self.values()[0]
        word = fmt == "docx"
        self.template_row.setVisible(word)
        templated = word and bool(self.template_path)
        # A template brings its own cover; its {{placeholders}} still use the details.
        self.cover.setEnabled(not templated)
        self.cover.setToolTip("The template has its own cover" if templated else
                              "A first page with the title, who it is for and by, the date and the finding counts")
        self.details.setVisible(self.cover.isChecked() or templated)
        self.title.setPlaceholderText(report.default_title(self._lab_name or "Lab", self.values()[1]))
        self.adjustSize()

    def front_matter(self) -> dict:
        """The cover and contents choices and details, as report.normalise_meta takes them."""
        templated = self.values()[0] == "docx" and bool(self.template_path)
        return {"cover": self.cover.isChecked() and not templated, "toc": self.toc.isChecked(),
                "title": self.title.text().strip(), "client": self.client.text().strip(),
                "author": self.author.text().strip(), "date": self.date.text().strip(),
                "cover_wanted": self.cover.isChecked()}

    def template(self) -> str:
        return self.template_path if self.values()[0] == "docx" else ""


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
