"""The lab snip list in the preview window."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

import preview


@pytest.fixture(scope="module")
def window():
    app = QApplication.instance() or QApplication([])
    win = preview.PreviewWindow()
    yield win
    win.close()
    app.processEvents()


ROWS = [
    {"file": "001_a.png", "number": 1, "time": "2026-09-27 19:01:10",
     "section": "box/nmap", "caption": "scan", "notes": ["ports"]},
    {"file": "002_b.png", "number": 2, "time": "2026-09-27 19:05:44",
     "section": "", "caption": "", "notes": []},
]


def _files(win):
    return [
        win.snips_list.topLevelItem(i).data(0, preview.Qt.ItemDataRole.UserRole)
        for i in range(win.snips_list.topLevelItemCount())
    ]


def test_newest_first_and_the_newest_selected(window):
    window.set_lab_snips(ROWS)
    assert _files(window) == ["002_b.png", "001_a.png"]
    assert window.selected_snip() == "002_b.png"
    assert window.btn_remove_snip.isEnabled()


def test_the_snip_on_screen_is_selected_and_marked(window):
    window.set_lab_snips(ROWS, current_file="001_a.png")
    assert window.selected_snip() == "001_a.png"
    assert "on screen" in window.snip_detail.text()
    assert "Filed under: box/nmap" in window.snip_detail.text()
    assert "Note: ports" in window.snip_detail.text()


def test_remove_emits_the_selected_file(window):
    window.set_lab_snips(ROWS)
    got = []
    window.snip_remove_requested.connect(got.append)
    window._emit_remove()
    window.snip_remove_requested.disconnect()
    assert got == ["002_b.png"]


def test_an_empty_lab_disables_the_buttons(window):
    window.set_lab_snips([])
    assert window.selected_snip() == ""
    assert not window.btn_remove_snip.isEnabled()
    assert "none yet" in window.snips_title.text()


def test_forgetting_the_snip_on_screen_drops_its_lab_actions(window):
    window.attach_lab(None, caption_cb=lambda text: True)
    window.forget_snip_on_screen()
    assert not window.caption.isVisibleTo(window)
    assert not window.btn_move_snip.isEnabled()
    assert not window.attach_note.isEnabled()


def test_a_refresh_keeps_the_selection_but_a_new_snip_takes_it(window):
    window.set_lab_snips(ROWS, current_file="002_b.png")
    window.snips_list.setCurrentItem(window.snips_list.topLevelItem(1))
    window.set_lab_snips(ROWS, current_file="002_b.png")  # a note was filed
    assert window.selected_snip() == "001_a.png"

    newer = ROWS + [{"file": "003_c.png", "number": 3, "time": "", "section": "",
                     "caption": "", "notes": []}]
    window.set_lab_snips(newer, current_file="003_c.png")
    assert window.selected_snip() == "003_c.png"


def test_the_snip_list_button_only_appears_during_a_lab(window):
    window.set_snips_visible(False, True)
    assert not window.btn_snips.isVisibleTo(window)
    assert not window.snips_shown()

    window.set_snips_visible(True, True)
    assert window.btn_snips.isVisibleTo(window)
    assert window.btn_snips.isChecked()
    assert window.snips_shown()


def test_the_snip_list_can_be_hidden_and_reports_it(window):
    window.set_snips_visible(True, True)
    got = []
    window.snip_list_toggled.connect(got.append)
    window.btn_snips.click()
    window.snip_list_toggled.disconnect()

    assert got == [False]
    assert not window.snips_shown()
    assert window.btn_snips.isVisibleTo(window)


def test_restoring_the_stored_state_does_not_echo_back(window):
    got = []
    window.snip_list_toggled.connect(got.append)
    window.set_snips_visible(True, False)
    window.snip_list_toggled.disconnect()

    assert got == []
    assert not window.snips_shown()
    assert not window.btn_snips.isChecked()
