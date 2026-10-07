"""The lab snip list follows the lab folder without a manual refresh."""

from __future__ import annotations

import time

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import app as app_mod
import clipboard
import config
import platforms
import lab


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(qapp)
    s.cfg["save_dir"] = str(tmp_path / "snips")
    yield s, qapp
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _pump(qapp, until, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


def _start_lab(s, name="box"):
    lab.start(s.cfg, name)
    s.cfg["active_lab"] = name
    s._refresh_menu_text()


def test_a_snip_appears_in_the_list_straight_away(shadow):
    s, qapp = shadow
    _start_lab(s)
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 90, 10))

    s._handle_snip(image)

    assert s.preview.snips_list.topLevelItemCount() == 1
    assert s.preview.selected_snip() == s._last_lab_file


def test_an_image_dropped_into_the_folder_shows_up_on_its_own(shadow):
    s, qapp = shadow
    _start_lab(s)
    assert s.preview.snips_list.topLevelItemCount() == 0

    (lab.active_folder(s.cfg) / "001_by-hand.png").write_bytes(b"x")

    assert _pump(qapp, lambda: s.preview.snips_list.topLevelItemCount() == 1)


def test_the_watch_follows_the_lab_and_stops_with_it(shadow):
    s, qapp = shadow
    _start_lab(s)
    assert s._lab_watcher.directories() == [str(lab.active_folder(s.cfg))]

    s.stop_lab()

    assert s._lab_watcher.directories() == []


def test_starting_a_lab_over_a_snip_lists_that_snip(shadow, monkeypatch):
    s, qapp = shadow
    s.cfg["show_preview"] = True
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(90, 10, 10))
    s._handle_snip(image)  # no lab yet
    monkeypatch.setattr(
        app_mod.QInputDialog, "getText", lambda *a, **k: ("box", True)
    )
    monkeypatch.setattr(s.preview, "isVisible", lambda: True)

    s.start_lab()

    assert s.preview.snips_list.topLevelItemCount() == 1


def test_the_lab_button_changes_colour_while_a_lab_runs(shadow):
    s, qapp = shadow
    assert not s.preview.lab_running()
    _start_lab(s)
    assert s.preview.lab_running()
    assert "box" in s.preview.btn_lab.text()
    s.stop_lab()
    assert not s.preview.lab_running()
    assert s.preview.btn_lab.text() == "Start lab"


def test_an_edit_in_the_snip_list_lands_in_the_lab(shadow):
    s, qapp = shadow
    _start_lab(s)
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 10, 90))
    s._handle_snip(image)
    panel = s.preview.snips_panel

    panel.caption_edit.setText("nmap full scan")
    panel.caption_edit.textEdited.emit("nmap full scan")
    panel.new_note.setPlainText("22 and 80 open")
    panel.save()

    assert lab.caption_of(s.cfg, s._last_lab_file) == "nmap full scan"
    (row,) = lab.snip_rows(s.cfg)
    assert row["notes"] == ["22 and 80 open"]
    assert _pump(qapp, lambda: panel.list.topLevelItem(0).text(3) == "nmap full scan")


def test_a_move_in_the_outline_lands_in_lab_md(shadow):
    s, qapp = shadow
    _start_lab(s)
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(50, 50, 50))
    s._handle_snip(image)
    first = s._last_lab_file
    lab.set_section(s.cfg, "host/smb")
    s._refresh_menu_text()

    s.preview.snips_panel.outline.move_requested.emit(f"snip:{first}", "host/smb", "")

    md = (lab.active_folder(s.cfg) / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert md.index("### smb") < md.index(first)
    assert _pump(
        qapp,
        lambda: any(
            item.data(0, 0x0100) == f"snip:{first}"
            and item.data(0, 0x0101) == "host/smb"
            for item in s.preview.snips_panel.outline._all_items()
        ),
    )
    assert "smb" in s.preview.snips_panel._md_text
