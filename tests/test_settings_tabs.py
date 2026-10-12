"""Settings is split into tabs and always fits the screen, so Save is reachable."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

import config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp, cfg):
    from settings_dialog import SettingsDialog

    d = SettingsDialog(cfg)
    yield d
    d.close()
    d.deleteLater()


def _tab_holding(dialog, widget) -> str:
    for i in range(dialog.tabs.count()):
        if dialog.tabs.widget(i).isAncestorOf(widget):
            return dialog.tabs.tabText(i)
    return ""


def test_five_tabs_in_order_opening_on_appearance(dialog):
    names = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert names == ["Appearance", "Snipping", "Image", "Copy on select", "Labs"]
    assert dialog.tabs.currentIndex() == 0


def test_every_tab_scrolls_if_the_screen_is_tiny(dialog):
    for i in range(dialog.tabs.count()):
        assert isinstance(dialog.tabs.widget(i), QScrollArea)


def test_settings_sit_on_the_right_tabs(dialog):
    assert _tab_holding(dialog, dialog.skin_combo) == "Appearance"
    assert _tab_holding(dialog, dialog.skin_next) == "Appearance"
    assert _tab_holding(dialog, dialog.preview_check) == "Appearance"
    assert _tab_holding(dialog, dialog.dim) == "Appearance"
    assert _tab_holding(dialog, dialog.hotkey_edit) == "Snipping"
    assert _tab_holding(dialog, dialog.format_combo) == "Image"
    assert _tab_holding(dialog, dialog.png_level) == "Image"
    assert _tab_holding(dialog, dialog.auto_copy_check) == "Copy on select"
    assert _tab_holding(dialog, dialog.lab_index_check) == "Labs"


def test_save_and_cancel_sit_outside_the_tabs(dialog):
    assert not dialog.tabs.isAncestorOf(dialog.buttons)
    assert dialog.isAncestorOf(dialog.buttons)


def test_dialog_fits_within_the_screen(dialog, qapp):
    dialog.show()
    qapp.processEvents()
    area = dialog.screen().availableGeometry()
    assert dialog.height() <= int(area.height() * 0.85)
    assert dialog.width() <= int(area.width() * 0.9)
    assert dialog.buttons.isVisible()


def test_values_still_round_trip_with_tabs(dialog):
    values = dialog.values()
    assert values["skin"] == "original"
    assert config._sanitise({**dict(config.DEFAULTS), **values})["skin"] == "original"
