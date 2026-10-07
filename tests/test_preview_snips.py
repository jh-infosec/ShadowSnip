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
     "section": "box/nmap", "caption": "scan", "notes": ["ports"],
     "note_entries": [{"id": "n001", "text": "ports"}], "recorded": True},
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
    panel = window.snips_panel
    assert "on screen" in panel.where.text()
    assert "box/nmap" in panel.where.text()


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
    assert not window.btn_move_snip.isEnabled()
    assert window._caption_cb is None
    assert not window.caption.isVisibleTo(window)
    assert not window.attach_note.isEnabled()


def test_the_caption_and_note_boxes_are_under_the_image(window):
    """Restored in 0.7.3: caption, notes, Add note and Attach for the snip on screen."""
    assert window.section_edit is not None
    assert window.note_edit is not None
    assert window.btn_note.text() == "Add note"
    assert window.attach_note.text() == "Attach to this snip"
    window.attach_lab(None, caption_cb=lambda text: True)
    assert window.caption.isVisibleTo(window)
    window.attach_lab(None, None)
    assert not window.caption.isVisibleTo(window)


def test_the_caption_starts_locked_and_unlocks_on_double_click(window):
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtTest import QTest

    window.attach_lab(None, caption_cb=lambda text: True)
    window.caption.setText("")
    window.caption.set_locked(True)
    assert window.caption.isReadOnly()
    QTest.mouseDClick(window.caption, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier, QPoint(5, 5))
    assert not window.caption.isReadOnly()
    # Sent directly: an offscreen window never becomes active.
    QApplication.sendEvent(window.caption, QFocusEvent(QEvent.Type.FocusOut))
    assert window.caption.isReadOnly()
    window.attach_lab(None, None)


def test_enter_in_the_caption_saves_once_and_locks(window):
    got = []
    window.attach_lab(None, caption_cb=lambda text: got.append(text) or True)
    window.caption.unlock()
    window.caption.setText("anonymous ftp")
    window.caption.returnPressed.emit()
    window.caption.editingFinished.emit()  # follows Enter; must not save twice
    assert got == ["anonymous ftp"]
    assert window.caption.isReadOnly()
    window.attach_lab(None, None)


def test_a_long_caption_shows_in_full_on_hover(window):
    window.attach_lab(None, caption_cb=lambda text: True)
    window.caption.setText("a very long caption " * 12)
    window.caption.resize(120, 28)
    window.caption._update_tooltip()
    tip = window.caption.toolTip()
    assert "a very long caption a very long caption" in tip
    assert "Double-click to edit" in tip
    window.caption.resize(2000, 28)
    window.caption.setText("short")
    assert window.caption.toolTip() == "Double-click to edit"
    window.attach_lab(None, None)


def test_add_note_emits_the_text_and_the_attach_choice(window):
    from PySide6.QtGui import QImage

    window.show()
    window.set_notes_visible(True)
    window._image = QImage(10, 10, QImage.Format.Format_RGB32)
    got = []
    window.note_added.connect(lambda text, attach: got.append((text, attach)))
    window.note_edit.setPlainText("22 and 80 open")
    window.attach_note.setEnabled(True)
    window.attach_note.setChecked(True)
    window.btn_note.click()
    window.note_added.disconnect()
    assert got == [("22 and 80 open", True)]
    window._image = None
    window.set_notes_visible(False)
    window.hide()


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


def test_the_version_is_shown_bottom_right(window):
    import config

    assert window.version.text() == f"ShadowSnip v{config.APP_VERSION}"



def test_the_tool_strip_is_there_from_the_start(window):
    import preview

    fresh = preview.PreviewWindow()
    fresh.show()
    assert fresh.tools.isVisible()
    assert not fresh.tools.buttons["pen"].isEnabled()
    fresh.close()


def test_esc_puts_a_tool_down_before_it_closes_the_window(window):
    window.show()
    window.tools.set_available(True)
    window.tools.select("redact")
    window._on_escape()
    assert window.tools.tool is None and window.isVisible()
    window._on_escape()
    assert not window.isVisible()
