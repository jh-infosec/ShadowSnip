"""Settings shows each skin as you cycle, before Save (0.8.0)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

import config
import skins


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_cycling_asks_for_a_picture_of_each_skin():
    from settings_dialog import SettingsDialog

    asked = []

    def picture(name):
        asked.append(name)
        pm = QPixmap(800, 500)
        pm.fill()
        return pm

    dialog = SettingsDialog(config._sanitise(dict(config.DEFAULTS)), skin_preview=picture)
    changed = []
    dialog.skin_changed.connect(changed.append)
    assert asked == ["original"]  # the current one, as Settings opens
    assert dialog.skin_picture.pixmap() is not None and not dialog.skin_picture.pixmap().isNull()
    dialog.skin_next.click()
    dialog.skin_next.click()
    assert changed == ["steel", "split"]
    assert asked == ["original", "steel", "split"]
    assert not dialog.skin_picture.isHidden()


def test_without_a_previewer_there_is_no_picture():
    from settings_dialog import SettingsDialog

    dialog = SettingsDialog(config._sanitise(dict(config.DEFAULTS)))
    assert dialog.skin_picture.isHidden()
    dialog.skin_next.click()  # still cycles, nothing breaks


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())
    yield s, app_mod
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _fake_dialog(answer, pick, previews):
    class Dialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, cfg, skin_preview=None):
            self.cfg = dict(cfg)
            self.preview = skin_preview

        def exec(self):
            for name in previews:
                picture = self.preview(name)
                assert not picture.isNull()
                assert skins.current() == name  # the window itself shows it too
            return answer

        def values(self):
            return {**self.cfg, "skin": pick}

    return Dialog


def test_cancel_puts_the_saved_skin_back(shadow, monkeypatch):
    s, app_mod = shadow
    monkeypatch.setattr(app_mod, "SettingsDialog", _fake_dialog(0, "split", ["steel", "console"]))
    s.open_settings()
    assert skins.current() == "original"
    assert config.load()["skin"] == "original"


def test_save_keeps_the_skin_chosen_not_the_last_previewed(shadow, monkeypatch):
    s, app_mod = shadow
    monkeypatch.setattr(app_mod, "SettingsDialog", _fake_dialog(1, "steel", ["console", "split"]))
    s.open_settings()
    assert skins.current() == "steel"
    assert config.load()["skin"] == "steel"
