"""The lab snip list follows the lab folder without a manual refresh."""

from __future__ import annotations

import time
from pathlib import Path

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


def test_a_caption_and_note_under_the_image_land_in_the_lab(shadow):
    s, qapp = shadow
    _start_lab(s)
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 10, 90))
    s._handle_snip(image)
    panel = s.preview.snips_panel

    s.preview.caption.unlock()
    s.preview.caption.setText("nmap full scan")
    s.preview.caption.returnPressed.emit()
    s.preview.note_edit.setPlainText("22 and 80 open")
    s.preview.attach_note.setChecked(True)
    s.preview.btn_note.click()

    assert lab.caption_of(s.cfg, s._last_lab_file) == "nmap full scan"
    (row,) = lab.snip_rows(s.cfg)
    assert row["notes"] == ["22 and 80 open"]
    assert s.preview.note_edit.toPlainText() == ""
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


def _three_snips(s):
    _start_lab(s)
    for colour in ((200, 0, 0), (0, 200, 0), (0, 0, 200)):
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        image.fill(QColor(*colour))
        s._handle_snip(image)
    return [row["file"] for row in lab.snip_rows(s.cfg)]


def test_several_snips_are_removed_after_one_question(shadow, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    s, qapp = shadow
    files = _three_snips(s)
    asked = []
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        lambda *a, **k: asked.append(a[1]) or QMessageBox.StandardButton.Yes,
    )
    s.remove_lab_snips(files[:2])
    assert asked == ["Remove 2 snips from lab"]
    assert [row["file"] for row in lab.snip_rows(s.cfg)] == files[2:]
    removed = lab.active_folder(s.cfg) / lab.REMOVED_DIR
    assert sorted(p.name for p in removed.iterdir()) == sorted(files[:2])


def test_saying_no_removes_nothing(shadow, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    s, qapp = shadow
    files = _three_snips(s)
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    s.remove_lab_snips(files)
    assert len(lab.snip_rows(s.cfg)) == 3


def test_a_lab_snip_is_copied_from_its_file(shadow, monkeypatch):
    s, qapp = shadow
    files = _three_snips(s)
    copied = []
    monkeypatch.setattr(clipboard, "copy", lambda png, image, **k: copied.append((png, image)))
    s.copy_lab_snip(files[0])
    (png, image), = copied
    assert png.startswith(b"\x89PNG")
    assert image.getpixel((5, 5))[:3] == (200, 0, 0)
    assert "copied" in s.preview.status.text()


# -- 0.7.7: editing lab snips in the full-size viewer -----------------------------------
def _black_middle(image):
    from PySide6.QtGui import QPainter

    # As the viewer's canvas does: a palette-reduced file loads as an indexed
    # image, which cannot be painted on directly.
    edited = image.convertToFormat(QImage.Format.Format_RGB32)
    painter = QPainter(edited)
    painter.fillRect(10, 10, 20, 15, QColor("black"))
    painter.end()
    return edited


def test_an_older_lab_snip_edited_in_the_viewer_is_saved_to_its_file(shadow):
    s, qapp = shadow
    files = _three_snips(s)
    folder = lab.active_folder(s.cfg)
    older = files[0]
    latest_before = (Path(s.cfg["save_dir"]) / "latest.png").read_bytes()

    s.save_lab_snip_edit(older, _black_middle(QImage(str(folder / older))))

    assert QImage(str(folder / older)).pixelColor(15, 15).name() == "#000000"
    # Only the lab file: latest.png belongs to the newest snip.
    assert (Path(s.cfg["save_dir"]) / "latest.png").read_bytes() == latest_before
    assert "Edit saved to snip" in s.preview.status.text()


def test_the_snip_on_screen_edited_in_the_viewer_updates_every_copy(shadow, monkeypatch):
    s, qapp = shadow
    files = _three_snips(s)
    folder = lab.active_folder(s.cfg)
    on_screen = s._last_lab_file
    assert on_screen == files[-1]
    copied = []
    monkeypatch.setattr(clipboard, "copy", lambda png, image, **k: copied.append(png))

    s.save_lab_snip_edit(on_screen, _black_middle(QImage(str(folder / on_screen))))

    assert QImage(str(folder / on_screen)).pixelColor(15, 15).name() == "#000000"
    latest = Path(s.cfg["save_dir"]) / "latest.png"
    assert QImage(str(latest)).pixelColor(15, 15).name() == "#000000"
    assert copied, "the clipboard copy is replaced too"
    # The preview window now starts from the edited snip, so drawing there
    # later cannot bring the original back.
    assert s.preview.canvas.image().pixelColor(15, 15).name() == "#000000"


def test_opening_the_snip_on_screen_in_the_viewer_saves_waiting_markup_first(shadow):
    s, qapp = shadow
    _three_snips(s)
    flushed = []
    s.preview.flush_edits = lambda: flushed.append(True) or False
    s._before_viewer_loads(s._last_lab_file)
    s._before_viewer_loads("001_other.png")
    assert flushed == [True]


def test_an_edit_is_refused_when_the_format_changed_since(shadow):
    s, qapp = shadow
    files = _three_snips(s)
    folder = lab.active_folder(s.cfg)
    before = (folder / files[0]).read_bytes()
    s.cfg["disk_format"] = "jpeg"
    s.save_lab_snip_edit(files[0], _black_middle(QImage(str(folder / files[0]))))
    assert (folder / files[0]).read_bytes() == before
    assert "kept as it was" in s.preview.status.text()
