"""Skins: Original, Steel and Split, chosen in Settings and applied live."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QApplication

import config
import skins


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- choosing --------------------------------------------------------------------------------
def test_three_skins_in_order_and_the_config_knows_them():
    assert skins.NAMES == ("original", "steel", "split")
    assert config.SKIN_NAMES == skins.NAMES
    assert [skins.LABELS[n] for n in skins.NAMES] == ["Original", "Steel", "Split"]


def test_next_cycles_through_all_three():
    assert skins.next_name("original") == "steel"
    assert skins.next_name("steel") == "split"
    assert skins.next_name("split") == "original"


@pytest.mark.parametrize("stored,expected", [
    (None, "original"), ("", "original"), ("STEEL", "steel"), (" split ", "split"),
    ("neon", "original"), (42, "original"),
])
def test_the_config_keeps_only_a_known_skin(stored, expected):
    cleaned = config._sanitise({**config.DEFAULTS, "skin": stored})
    assert cleaned["skin"] == expected


def test_original_is_the_default():
    assert config.DEFAULTS["skin"] == "original"


# -- colours and stylesheets -------------------------------------------------------------------
def test_original_leaves_every_stylesheet_and_colour_alone():
    import preview

    assert skins.style(preview.STYLE) == preview.STYLE
    assert skins.color("#101013").name() == "#101013"
    assert skins.accent() == "#2f8cff"
    assert skins.paint_background(200, 100) is None


@pytest.mark.parametrize("name", ["steel", "split"])
def test_a_skin_recolours_and_adds_its_own_rules(name):
    import preview

    skins.set_current(name)
    css = skins.style(preview.STYLE)
    assert css != preview.STYLE
    assert "#1b1b1f" not in css           # the original window colour is replaced
    assert "QTabBar::tab:selected" in css  # the skin's own rules are on top
    assert "border-radius: 4px; padding: 6px 14px" in css  # the original button shape
    assert skins.accent() == skins.RED


def test_painted_colours_follow_the_skin_and_others_are_left_alone():
    skins.set_current("steel")
    assert skins.color("#101013").name() != "#101013"
    assert skins.color("#e81123").name() == "#e81123"  # a pen colour is never a skin colour


@pytest.mark.parametrize("name", ["steel", "split"])
def test_the_background_is_painted_at_the_window_size(name):
    skins.set_current(name)
    image = skins.paint_background(640, 400)
    assert (image.width(), image.height()) == (640, 400)
    top, bottom = image.pixelColor(320, 20), image.pixelColor(320, 380)
    assert top != bottom  # a gradient, not a flat fill


def test_split_has_a_red_seam():
    skins.set_current("split")
    image = skins.paint_background(800, 500)
    # The seam runs corner to corner; the middle sits on it.
    on_seam = image.pixelColor(400, 225)
    beside = image.pixelColor(400, 120)
    assert on_seam.red() - on_seam.blue() > beside.red() - beside.blue()


def test_the_selected_row_uses_the_skin_accent():
    import labsnips

    fill, edge = labsnips.select_colours()
    assert edge.name() == labsnips.SELECT_EDGE.lower()
    skins.set_current("steel")
    fill, edge = labsnips.select_colours()
    assert edge.name() == skins.RED


# -- the window --------------------------------------------------------------------------------
@pytest.fixture
def window():
    import preview
    from app import build_icon

    win = preview.PreviewWindow(icon=build_icon())
    win.resize(900, 600)
    win.show()
    yield win
    win.close()


def test_switching_skins_live_and_back(window):
    import preview

    assert window.styleSheet() == preview.STYLE
    assert not window.brand.isVisibleTo(window)
    assert window.btn_new.graphicsEffect() is None

    skins.set_current("steel")
    window.apply_skin()
    assert window.styleSheet() != preview.STYLE
    assert window.brand.isVisibleTo(window)
    assert window.btn_new.graphicsEffect() is not None
    window.grab()  # paints the background
    assert window._skin_bg is not None and window._skin_bg.size() == window.size()

    skins.set_current("original")
    window.apply_skin()
    assert window.styleSheet() == preview.STYLE
    assert not window.brand.isVisibleTo(window)
    assert window.btn_new.graphicsEffect() is None


def test_the_lab_button_glows_only_while_a_lab_records(window):
    skins.set_current("split")
    window.apply_skin()
    assert window.btn_lab.graphicsEffect() is None
    window.set_lab_name("htb-lame")
    assert window.btn_lab.graphicsEffect() is not None
    window.set_lab_name("")
    assert window.btn_lab.graphicsEffect() is None


def test_the_background_follows_a_resize(window):
    skins.set_current("steel")
    window.apply_skin()
    window.grab()
    window.resize(1000, 700)
    window.grab()
    assert window._skin_bg.size() == window.size()


def test_the_tool_strip_and_viewer_follow_the_skin(window):
    import annotate

    skins.set_current("steel")
    window.apply_skin()
    assert window.tools.styleSheet() != annotate.STRIP_STYLE


# -- settings ----------------------------------------------------------------------------------
def test_settings_offers_the_three_and_next_cycles():
    from settings_dialog import SettingsDialog

    dialog = SettingsDialog(config._sanitise(dict(config.DEFAULTS)))
    combo = dialog.skin_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Original", "Steel", "Split"]
    assert dialog.values()["skin"] == "original"
    dialog.skin_next.click()
    assert dialog.values()["skin"] == "steel"
    dialog.skin_next.click()
    assert dialog.values()["skin"] == "split"
    assert "seam" in dialog.skin_about.text()
    dialog.skin_next.click()
    assert dialog.values()["skin"] == "original"


def test_the_saved_skin_is_used_at_startup(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms

    path = tmp_path / "cfg" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"skin": "split"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())
    try:
        assert skins.current() == "split"
        assert s.preview.brand.isVisibleTo(s.preview)
    finally:
        s.autocopy.release()
        s.preview.close()
        s.tray.hide()


def test_settings_switches_the_skin_live(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms
    import preview

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())

    class Dialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, cfg):
            self.cfg = dict(cfg)

        def exec(self):
            return 1

        def values(self):
            return {**self.cfg, "skin": "steel"}

    monkeypatch.setattr(app_mod, "SettingsDialog", Dialog)
    try:
        s.open_settings()
        assert skins.current() == "steel"
        assert s.preview.styleSheet() != preview.STYLE
        assert config.load()["skin"] == "steel"
    finally:
        s.autocopy.release()
        s.preview.close()
        s.tray.hide()
