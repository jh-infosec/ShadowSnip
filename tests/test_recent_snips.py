"""Outside a lab, the snip list shows your recent snips (0.8.0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

import config
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- the config ---------------------------------------------------------------------------------
def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_an_older_config_gets_history_switched_on_once(isolated_config):
    _write(isolated_config, {"keep_history": False})
    loaded = config.load()
    assert loaded["keep_history"] is True
    assert loaded["history_reviewed"] is True


def test_switching_history_off_afterwards_is_kept(isolated_config):
    cfg = config.load()
    cfg["keep_history"] = False
    config.save(cfg)
    assert config.load()["keep_history"] is False


# -- the app -----------------------------------------------------------------------------------
@pytest.fixture
def shadow(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())
    s.cfg["save_dir"] = str(tmp_path / "snips")
    s.cfg["keep_history"] = True
    s._refresh_menu_text()
    yield s
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _image(colour="#336699"):
    img = QImage(120, 80, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


def test_snips_without_a_lab_fill_the_recent_list(shadow):
    panel = shadow.preview.snips_panel
    assert shadow.preview.btn_snips.isVisibleTo(shadow.preview)
    assert not panel.is_lab_mode()
    shadow._handle_snip(_image())
    shadow._handle_snip(_image("#993366"))
    assert panel.list.topLevelItemCount() == 2
    assert panel.title.text() == "Recent snips (2)"
    # The newest is on top and marked as the one on screen.
    top = panel.list.topLevelItem(0)
    assert top.text(0).endswith("*")
    assert panel.selected() == shadow._last_history_file


def test_a_recent_snip_can_be_copied_opened_and_removed(shadow, monkeypatch):
    import app as app_mod

    shadow._handle_snip(_image())
    shadow._handle_snip(_image("#993366"))
    older = storage.history_rows(shadow.cfg)[0]["file"]

    copied = []
    monkeypatch.setattr(app_mod.clipboard, "copy", lambda png, *a, **k: copied.append(png))
    shadow.copy_lab_snip(older)
    assert copied and copied[0].startswith(b"\x89PNG")

    opened = []
    monkeypatch.setattr(app_mod.storage, "open_file", lambda path: opened.append(Path(path)))
    shadow.open_lab_snip(older)
    assert opened == [storage.history_folder(shadow.cfg) / older]

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    shadow.remove_lab_snips([older])
    assert [r["file"] for r in storage.history_rows(shadow.cfg)] == [shadow._last_history_file]
    assert (storage.history_folder(shadow.cfg) / storage.REMOVED_DIRNAME / older).is_file()
    assert shadow.preview.snips_panel.list.topLevelItemCount() == 1


def test_starting_a_lab_switches_to_the_lab_list_and_back(shadow):
    import lab

    shadow._handle_snip(_image())
    panel = shadow.preview.snips_panel
    assert not panel.is_lab_mode()
    lab.start(shadow.cfg, "box")
    shadow.cfg["active_lab"] = "box"
    shadow._refresh_menu_text()
    assert panel.is_lab_mode()
    assert panel.list.topLevelItemCount() == 0  # nothing in the lab yet
    lab.stop(shadow.cfg)
    shadow._refresh_menu_text()
    assert not panel.is_lab_mode()
    assert panel.list.topLevelItemCount() == 1
