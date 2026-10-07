"""An edited snip replaces every copy: clipboard, latest, lab, history.

A redaction that reached only some of them would leave the original pixels
in the others, so each copy is checked for the redacted area.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import annotate as an
import app as app_mod
import clipboard
import config
import lab
import platforms


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    copies = []
    monkeypatch.setattr(clipboard, "copy", lambda png, image, **k: copies.append(image))
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(qapp)
    s.cfg["save_dir"] = str(tmp_path / "snips")
    s.cfg["show_preview"] = True
    s.cfg["quantize"] = False  # keep colours exact for pixel checks
    s.copies = copies
    yield s
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _white():
    img = QImage(300, 160, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    return img


def _redact(s, rect=QRect(20, 20, 120, 60)):
    canvas = s.preview.canvas
    canvas.doc.add(an.Redact(canvas.doc.new_id(), rect, "black"))
    canvas._refresh()
    canvas.edited.emit()


def _blacked_out(path, x=60, y=40):
    return QImage(str(path)).pixelColor(x, y).name() == "#000000"


def test_an_edit_waits_then_saves(shadow):
    shadow._handle_snip(_white())
    _redact(shadow)
    assert shadow.preview._edit_timer.isActive()
    assert shadow.preview.flush_edits() is True
    assert shadow.preview.flush_edits() is False  # nothing left to save


def test_a_redaction_reaches_the_lab_and_latest_copies(shadow):
    lab.start(shadow.cfg, "box")
    shadow.cfg["active_lab"] = "box"
    shadow._handle_snip(_white())
    lab_file = lab.active_folder(shadow.cfg) / shadow._last_lab_file
    latest = shadow._snip_paths["latest"]
    assert not _blacked_out(lab_file) and not _blacked_out(latest)

    _redact(shadow)
    shadow.preview.flush_edits()

    assert _blacked_out(lab_file)
    assert _blacked_out(latest)
    assert shadow.copies[-1].convert("RGB").getpixel((60, 40)) == (0, 0, 0)
    assert "Edit saved" in shadow.preview.status.text()


def test_a_redaction_reaches_the_history_copy(shadow):
    shadow.cfg["keep_history"] = True
    shadow._handle_snip(_white())
    history = shadow._snip_paths["history"]
    _redact(shadow)
    shadow.preview.flush_edits()
    assert _blacked_out(history)


def test_a_crop_changes_the_saved_size(shadow):
    shadow._handle_snip(_white())
    canvas = shadow.preview.canvas
    canvas.doc.add(an.Crop(canvas.doc.new_id(), QRect(10, 10, 100, 50)))
    canvas.edited.emit()
    shadow.preview.flush_edits()
    saved = QImage(str(shadow._snip_paths["latest"]))
    assert (saved.width(), saved.height()) == (100, 50)
    assert shadow.preview._disk_bytes  # Save as writes the edited bytes


def test_a_new_snip_saves_pending_edits_to_the_old_one_first(shadow, monkeypatch):
    shadow._handle_snip(_white())
    old_latest_bytes_before = shadow._snip_paths["latest"].read_bytes()
    _redact(shadow)
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda *_a: None)
    shadow.request_snip()
    assert not shadow.preview._edit_timer.isActive()
    assert shadow._snip_paths["latest"].read_bytes() != old_latest_bytes_before
    assert _blacked_out(shadow._snip_paths["latest"])
    shadow.busy = False


def test_a_removed_lab_snip_is_not_recreated_by_an_edit(shadow, monkeypatch):
    lab.start(shadow.cfg, "box")
    shadow.cfg["active_lab"] = "box"
    shadow._handle_snip(_white())
    filename = shadow._last_lab_file
    monkeypatch.setattr(
        app_mod.QMessageBox, "question",
        lambda *a, **k: app_mod.QMessageBox.StandardButton.Yes,
    )
    shadow.remove_lab_snip(filename)
    _redact(shadow)
    shadow.preview.flush_edits()
    assert not (lab.active_folder(shadow.cfg) / filename).exists()


def test_tool_settings_are_remembered(shadow):
    shadow.preview.tools._set_prefs(pen_color="#16c60c", pen_width=9)
    assert shadow.cfg["annotation"]["pen_color"] == "#16c60c"
    assert config.load()["annotation"]["pen_width"] == 9


def test_a_new_snip_has_no_tool_in_hand(shadow):
    shadow._handle_snip(_white())
    shadow.preview.tools.select("pen")
    shadow._handle_snip(_white())
    assert shadow.preview.tools.tool is None and shadow.preview.canvas.tool is None


def test_save_as_from_the_menu_writes_the_edited_snip(shadow, tmp_path, monkeypatch):
    shadow._handle_snip(_white())
    _redact(shadow)  # still waiting to be saved
    target = tmp_path / "kept.png"
    import preview

    monkeypatch.setattr(
        preview.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )
    shadow.preview.canvas.save_as_requested.emit()
    assert _blacked_out(target)
