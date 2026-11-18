"""The windows for encrypted labs (0.16.0): start, unlock, the recovery key, a new password.

They only collect what is typed and show what they are given; `vault.py`
does the cryptography and app.py the filing. The unlock window tries the
password itself (through the function it is given), so a wrong one is said
in place and the window stays open for another go.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import vault


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("FieldLabel")
    return label


def _error() -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setStyleSheet("color: #ff6b6b;")
    label.hide()
    return label


def _password_box(placeholder: str) -> QLineEdit:
    box = QLineEdit()
    box.setEchoMode(QLineEdit.EchoMode.Password)
    box.setPlaceholderText(placeholder)
    return box


def _mono() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class NewPassword(QWidget):
    """A password typed twice, with what is wrong with it shown as you type."""

    def __init__(self, first: str = "Password", parent=None):
        super().__init__(parent)
        self.password = _password_box(f"At least {vault.MIN_PASSWORD} characters")
        self.again = _password_box("The same again")
        self.problem = _hint("")
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(first, self.password)
        form.addRow("Again", self.again)
        form.addRow("", self.problem)
        for box in (self.password, self.again):
            box.textChanged.connect(self._check)
        self._check()

    def value(self) -> str:
        return self.password.text()

    def ok(self) -> bool:
        return not vault.password_problem(self.password.text(), self.again.text())

    def _check(self) -> None:
        text, again = self.password.text(), self.again.text()
        if not text:
            message = "A long passphrase of a few words is easier to type and harder to guess."
        elif len(text) < vault.MIN_PASSWORD:
            message = vault.password_problem(text)
        elif again and again != text:
            message = "The two are not the same yet."
        else:
            message = "There is no way to open the lab without this or the recovery key."
        self.problem.setText(message)


class StartLabDialog(QDialog):
    """A lab's name, and for a new one whether to encrypt it and with what password."""

    def __init__(self, name: str = "", encrypt_default: bool = False, exists=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Start lab")
        self.setMinimumWidth(440)
        self._exists = exists or (lambda _name: False)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("lame, or htb-lame, or client-acme")
        self.encrypt = QCheckBox("Encrypt this lab")
        self.encrypt.setToolTip("Every file in the lab folder encrypted at rest, opened with a password")
        self.encrypt.setChecked(bool(encrypt_default) and vault.available())
        self.encrypt.setEnabled(vault.available())
        self.passwords = NewPassword()
        self.note = _hint("")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_start = buttons.addButton("Start", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_start.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Lab name", self.name)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.encrypt)
        layout.addWidget(self.passwords)
        layout.addWidget(self.note)
        layout.addWidget(buttons)
        for signal in (self.name.textChanged, self.encrypt.toggled,
                       self.passwords.password.textChanged, self.passwords.again.textChanged):
            signal.connect(self._sync)
        self._sync()

    def is_new(self) -> bool:
        return bool(self.name.text().strip()) and not self._exists(self.name.text().strip())

    def _sync(self, *_args) -> None:
        new = self.is_new()
        self.encrypt.setVisible(new or not self.name.text().strip())
        wanted = self.encrypt.isChecked() and not self.encrypt.isHidden()
        self.passwords.setVisible(wanted)
        if not vault.available():
            self.note.setText("Encrypted labs need the cryptography package: pip install cryptography")
        elif self.name.text().strip() and not new:
            self.note.setText("Resumes this lab. Encrypt or decrypt a lab from the tray menu while it runs.")
        elif wanted:
            self.note.setText("You will be shown a recovery key next. It opens the lab if the password is forgotten.")
        else:
            self.note.setText("")
        self.btn_start.setEnabled(bool(self.name.text().strip()) and (not wanted or self.passwords.ok()))
        self.adjustSize()

    def values(self) -> tuple[str, bool, str]:
        """(name, encrypt, password); password '' when not encrypting."""
        wanted = self.encrypt.isChecked() and self.is_new()
        return self.name.text().strip(), wanted, self.passwords.value() if wanted else ""


class UnlockDialog(QDialog):
    """The password (or the recovery key) for an encrypted lab, tried before closing."""

    def __init__(self, lab_name: str, try_unlock, parent=None):
        """`try_unlock(password=..., recovery=...)` raises vault.VaultError when it does not open."""
        super().__init__(parent)
        self.setWindowTitle(f"Unlock {lab_name}")
        self.setMinimumWidth(420)
        self._try = try_unlock
        self.recovered = False
        self.password = _password_box("The lab's password")
        self.recovery = QLineEdit()
        self.recovery.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        self.recovery.setFont(_mono())
        self.recovery.hide()
        self.use_recovery = QPushButton("Use the recovery key instead")
        self.use_recovery.setFlat(True)
        self.use_recovery.setCursor(Qt.CursorShape.PointingHandCursor)
        self.use_recovery.clicked.connect(self._toggle_recovery)
        self.error = _error()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_unlock = buttons.addButton("Unlock", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_unlock.setDefault(True)
        buttons.accepted.connect(self._attempt)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(f"{lab_name} is encrypted. Its snips, notes and lab.md open with its password."))
        layout.addWidget(self.password)
        layout.addWidget(self.recovery)
        layout.addWidget(self.use_recovery, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.password.setFocus()

    def _toggle_recovery(self) -> None:
        using = not self.recovery.isVisible()
        self.recovery.setVisible(using)
        self.password.setVisible(not using)
        self.use_recovery.setText("Use the password instead" if using else "Use the recovery key instead")
        self.error.hide()
        (self.recovery if using else self.password).setFocus()

    def _attempt(self) -> None:
        using_recovery = self.recovery.isVisible()
        try:
            if using_recovery:
                self._try(recovery=self.recovery.text())
            else:
                self._try(password=self.password.text())
        except vault.WrongKey:
            self.error.setText("That recovery key does not open this lab." if using_recovery
                               else "That password does not open this lab.")
            self.error.show()
            (self.recovery if using_recovery else self.password).selectAll()
            return
        except vault.VaultError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.recovered = using_recovery
        self.accept()


class RecoveryKeyDialog(QDialog):
    """The recovery key, shown once, kept on screen until you say it is saved."""

    def __init__(self, lab_name: str, key: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Recovery key for {lab_name}")
        self.setMinimumWidth(500)
        self.key = key
        shown = QLineEdit(key)
        shown.setReadOnly(True)
        font = _mono()
        font.setPointSizeF(font.pointSizeF() * 1.25)
        shown.setFont(font)
        shown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy)
        self.saved = QCheckBox("I have saved it somewhere safe, away from this computer")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setEnabled(False)
        self.saved.toggled.connect(self.btn_ok.setEnabled)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(
            "This key opens the lab if the password is forgotten. It is shown only "
            "now: ShadowSnip does not keep a copy. Put it in your password manager."))
        layout.addWidget(shown)
        layout.addWidget(self.btn_copy, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.saved)
        layout.addWidget(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.key)
        self.btn_copy.setText("Copied")

    def reject(self) -> None:
        # Esc must not throw the only copy away unseen.
        if self.saved.isChecked():
            super().reject()


class PasswordDialog(QDialog):
    """A new password for an encrypted lab, or for encrypting one."""

    def __init__(self, title: str, intro: str, ask_current: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.current = _password_box("The password it opens with now") if ask_current else None
        self.passwords = NewPassword("New password" if ask_current else "Password")
        self.error = _error()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_ok = buttons.addButton(title.rstrip("."), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(_hint(intro))
        if self.current is not None:
            form = QFormLayout()
            form.addRow("Current password", self.current)
            layout.addLayout(form)
        layout.addWidget(self.passwords)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        for box in (self.passwords.password, self.passwords.again):
            box.textChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        self.btn_ok.setEnabled(self.passwords.ok())

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()

    def values(self) -> tuple[str, str]:
        """(current, new)."""
        return (self.current.text() if self.current is not None else ""), self.passwords.value()
