"""Quitting: easy to do on purpose, hard to do by accident (0.8.3)."""

from __future__ import annotations

import os
import signal
import sys

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox

import config


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())
    quits = []
    monkeypatch.setattr(s, "quit", lambda: quits.append(True))
    s._quits = quits
    yield s
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _answer(monkeypatch, choose_quit: bool):
    def exec_(box):
        if choose_quit:
            box.defaultButton().click()
        else:
            box.button(QMessageBox.StandardButton.Cancel).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_)


def test_ctrl_q_in_the_window_asks_to_quit(shadow, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: asked.append(box.text()) or 0)
    keys = [s.key().toString() for s in shadow.preview.findChildren(QShortcut)]
    assert QKeySequence("Ctrl+Q").toString() in keys
    got = []
    shadow.preview.quit_requested.connect(lambda: got.append(True))
    for sc in shadow.preview.findChildren(QShortcut):
        if sc.key() == QKeySequence("Ctrl+Q"):
            sc.activated.emit()
    assert got == [True]
    assert asked == ["Quit ShadowSnip?"]
    assert shadow._quits == []  # nothing chosen, nothing quit


def test_quit_is_the_default_answer(shadow, monkeypatch):
    _answer(monkeypatch, choose_quit=True)
    shadow.confirm_quit()
    assert shadow._quits == [True]


def test_cancel_keeps_it_running(shadow, monkeypatch):
    _answer(monkeypatch, choose_quit=False)
    shadow.confirm_quit()
    assert shadow._quits == []


def test_closing_the_window_says_once_where_shadowsnip_went(shadow, monkeypatch):
    shown = []
    monkeypatch.setattr(shadow.tray, "showMessage", lambda *a, **k: shown.append(a[0]))
    shadow.preview.show()
    shadow.preview.close()
    assert shown == ["ShadowSnip is still running"]
    assert config.load()["close_hint_shown"] is True
    shadow.preview.show()
    shadow.preview.close()
    assert len(shown) == 1  # once, ever
    assert shadow._quits == []  # closing the window never quits


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_ctrl_c_or_kill_quits_cleanly(signum, qapp):
    import main

    quits = []

    class Shadow:
        def quit(self):
            quits.append(True)

    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        main._quit_on_signals(qapp, Shadow())
        QTimer.singleShot(50, lambda: os.kill(os.getpid(), signum))
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.start(2000)
        while not quits and deadline.isActive():
            qapp.processEvents()
        assert quits == [True]
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
        qapp._signal_pulse.stop()
