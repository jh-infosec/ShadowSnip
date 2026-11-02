"""Right-click a snip in the list or its picture (0.10.2)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu

import labsnips as ls
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    for i, stamp in enumerate(["2026-10-29_09-14-03", "2026-10-30_10-00-00", "2026-10-31_11-02-45"]):
        img = QImage(200, 120, QImage.Format.Format_RGB32)
        img.fill(QColor("#336699"))
        path = hist / f"snip_{stamp}.png"
        img.save(str(path))
        os.utime(path, (time.time() + i, time.time() + i))
    widget = ls.LabSnipsPanel()
    widget.set_lab_mode(False)
    widget.resize(600, 500)
    widget.show()
    rows = storage.history_rows({"save_dir": str(tmp_path)})
    widget.set_rows(rows, rows[-1]["file"])
    QApplication.processEvents()
    yield widget
    widget.close()


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _action(menu: QMenu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


def test_menu_offers_the_snip_actions(panel):
    menu = panel.snip_menu()
    assert _texts(menu) == ["Expand", "Copy", "Save as...", "Open", "Show in folder", "Remove..."]
    assert _action(menu, "Copy").shortcut().toString() == "Ctrl+C"
    assert all(a.isEnabled() for a in menu.actions() if not a.isSeparator())


def test_menu_in_a_lab_says_remove_from_lab(panel):
    panel.set_lab_mode(True)
    rows = [{"file": "a.png", "number": 1, "time": "", "path": "", "section": "",
             "caption": "", "notes": []}]
    panel.set_rows(rows, "a.png")
    assert "Remove from lab..." in _texts(panel.snip_menu())


def test_copy_from_the_menu_asks_the_app_for_that_snip(panel):
    copied = []
    panel.copy_requested.connect(copied.append)
    _action(panel.snip_menu(), "Copy").trigger()
    assert copied == [panel.selected()]


def test_remove_from_the_menu_takes_every_selected_snip(panel):
    removed = []
    panel.remove_requested.connect(removed.append)
    for index in range(panel.list.topLevelItemCount()):
        panel.list.topLevelItem(index).setSelected(True)
    menu = panel.snip_menu()
    assert "Remove 3..." in _texts(menu)
    _action(menu, "Remove 3...").trigger()
    assert len(removed[0]) == 3


def _right_click_row(panel, row: int, monkeypatch) -> list:
    shown = []
    monkeypatch.setattr(panel, "_popup", lambda menu, where: shown.append(_texts(menu)))
    rect = panel.list.visualItemRect(panel.list.topLevelItem(row))
    panel.list.customContextMenuRequested.emit(rect.center())
    return shown


def test_right_click_outside_the_selection_selects_that_snip(panel, monkeypatch):
    first = panel.selected()
    shown = _right_click_row(panel, 2, monkeypatch)
    assert shown and panel.selected() != first
    assert panel.selected_files() == [panel.selected()]


def test_right_click_inside_a_selection_keeps_it(panel, monkeypatch):
    for index in (0, 1):
        panel.list.topLevelItem(index).setSelected(True)
    _right_click_row(panel, 1, monkeypatch)
    assert len(panel.selected_files()) == 2


def test_right_click_on_empty_space_shows_nothing(panel, monkeypatch):
    shown = []
    monkeypatch.setattr(panel, "_popup", lambda menu, where: shown.append(True))
    panel.list.customContextMenuRequested.emit(QPoint(5, panel.list.viewport().height() - 2))
    assert shown == []


def test_the_picture_has_the_same_menu(panel, monkeypatch):
    shown = []
    monkeypatch.setattr(panel, "_popup", lambda menu, where: shown.append(_texts(menu)))
    panel.thumb.customContextMenuRequested.emit(QPoint(10, 10))
    assert shown and shown[0][1] == "Copy"
    assert panel.thumb.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_save_as_writes_a_copy(panel, tmp_path, monkeypatch):
    target = tmp_path / "out" / "evidence.png"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    messages = []
    panel.status_message.connect(messages.append)
    panel.save_selected_as()
    source = Path(panel._rows[panel.selected()]["path"])
    assert target.read_bytes() == source.read_bytes()
    assert messages[-1].startswith("Saved to")


def test_show_in_folder_opens_the_snips_folder(panel, monkeypatch):
    opened = []
    monkeypatch.setattr(ls, "show_in_folder", opened.append)
    panel.show_selected_in_folder()
    assert opened == [Path(panel._rows[panel.selected()]["path"])]


def test_a_missing_file_says_so(panel, monkeypatch):
    Path(panel._rows[panel.selected()]["path"]).unlink()
    messages = []
    panel.status_message.connect(messages.append)
    panel.show_selected_in_folder()
    assert "no longer there" in messages[-1]
