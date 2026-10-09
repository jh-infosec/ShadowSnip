"""Thumbnails, the detail view and the viewer in the lab snip list."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import labsnips


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def rows(tmp_path):
    out = []
    for number, colour in ((1, "red"), (2, "green"), (3, "blue")):
        path = tmp_path / f"{number:03d}_snip.png"
        image = QImage(400, 250, QImage.Format.Format_RGB32)
        image.fill(QColor(colour))
        image.save(str(path))
        out.append(
            {
                "file": path.name,
                "number": number,
                "time": f"2026-09-28 20:0{number}:00",
                "section": "box/smb" if number == 2 else "",
                "caption": f"caption {number}",
                "notes": [f"note {number}"],
                "note_entries": [{"id": f"n00{number}", "text": f"note {number}"}],
                "path": str(path),
                "recorded": True,
            }
        )
    return out


@pytest.fixture
def panel(rows):
    widget = labsnips.LabSnipsPanel()
    widget.resize(420, 600)
    widget.show()
    widget.set_rows(rows, current_file="003_snip.png")
    yield widget
    widget.hide_viewer()
    widget.close()


def test_rows_have_no_mini_thumbnails(panel):
    """Too small to read; the selected snip's preview is right underneath."""
    for index in range(panel.list.topLevelItemCount()):
        assert panel.list.topLevelItem(index).icon(0).isNull()


def test_the_list_does_not_use_the_platform_selection_colour(panel):
    """The Windows 11 style paints selection in the accent colour, red on some machines."""
    from PySide6.QtGui import QPalette

    assert panel.list._fusion is not None  # the stylesheet wraps it, so name() is empty
    highlight = panel.list.palette().color(QPalette.ColorRole.Highlight)
    assert (highlight.red(), highlight.green(), highlight.blue()) == labsnips.SELECT_FILL[:3]


def test_the_selected_snip_shows_a_thumbnail_and_its_words(panel):
    assert panel.selected() == "003_snip.png"
    assert panel.thumb.pixmap() is not None and not panel.thumb.pixmap().isNull()
    assert "on screen" in panel.where.text() and "2026-09-28 20:03:00" in panel.where.text()


def test_the_panel_has_no_caption_or_note_editors(panel):
    """Captions and notes are written under the image, not beside it (0.7.3)."""
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

    for name in ("caption_edit", "new_note", "_note_editors", "btn_save", "save", "flush"):
        assert not hasattr(panel, name), name
    editors = panel.findChildren(QLineEdit) + panel.findChildren(QPlainTextEdit)
    assert [e for e in editors if e.isVisible() and not e.isReadOnly()] == []


def test_moving_between_snips_changes_the_thumbnail(panel):
    first = panel.thumb.pixmap().toImage().pixelColor(20, 20)
    panel.select("001_snip.png")
    assert panel.selected() == "001_snip.png"
    assert panel.thumb.pixmap().toImage().pixelColor(20, 20) != first


def test_hover_shows_a_bigger_preview(panel):
    tip = panel.list.topLevelItem(0).toolTip(0)
    assert "<img " in tip and "003_snip.png" in tip
    assert "caption 3" in tip


def test_expand_opens_the_viewer_on_the_selected_snip_and_cycles(panel):
    panel.select("002_snip.png")
    panel.expand()
    viewer = panel.viewer
    assert viewer.isVisible()
    assert viewer.current_file() == "002_snip.png"

    viewer.step(1)
    assert viewer.current_file() == "003_snip.png"
    assert panel.selected() == "003_snip.png"  # the list follows

    viewer.step(1)  # already at the newest
    assert viewer.current_file() == "003_snip.png"

    viewer.step(-2)
    assert panel.selected() == "001_snip.png"


def test_clicking_the_thumbnail_expands(panel):
    panel.thumb.clicked.emit()
    assert panel.viewer is not None and panel.viewer.isVisible()


def test_the_thumb_cache_reloads_a_changed_file(rows, tmp_path):
    cache = labsnips.ThumbCache()
    path = rows[0]["path"]
    first = cache.get(path, QSize(56, 34))
    assert cache.get(path, QSize(56, 34)) is first
    cache.keep_only([])
    assert cache._cache == {}


# -- 0.7.5: several at once, and copy or remove from the viewer ------------------------
def _select_range(panel, first: int, last: int) -> None:
    """A click on one row, then a shift-click on another."""
    from PySide6.QtCore import QItemSelectionModel

    panel.list.setCurrentItem(panel.list.topLevelItem(first))
    model = panel.list.selectionModel()
    for index in range(first, last + 1):
        item = panel.list.topLevelItem(index)
        model.select(panel.list.indexFromItem(item),
                     QItemSelectionModel.SelectionFlag.Select
                     | QItemSelectionModel.SelectionFlag.Rows)


def test_the_list_allows_shift_and_ctrl_click(panel):
    from PySide6.QtWidgets import QAbstractItemView

    assert panel.list.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


def test_shift_click_on_a_row_selects_the_range(panel):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    rect_first = panel.list.visualItemRect(panel.list.topLevelItem(0))
    rect_last = panel.list.visualItemRect(panel.list.topLevelItem(2))
    viewport = panel.list.viewport()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     rect_first.center())
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                     rect_last.center())
    assert panel.selected_files() == ["003_snip.png", "002_snip.png", "001_snip.png"]


def test_removing_several_sends_them_all_in_one_request(panel):
    got = []
    panel.remove_requested.connect(got.append)
    _select_range(panel, 0, 1)
    panel._emit_remove()
    assert got == [["003_snip.png", "002_snip.png"]]
    assert panel.btn_remove.text() == "Remove 2 from lab"


def test_one_selected_keeps_the_plain_button(panel):
    panel.select("002_snip.png")
    assert panel.selected_files() == ["002_snip.png"]
    assert panel.btn_remove.text() == "Remove from lab"


def test_a_refresh_keeps_a_multi_selection(panel, rows):
    _select_range(panel, 0, 2)
    panel.set_rows(rows, current_file="003_snip.png")
    assert len(panel.selected_files()) == 3


def test_the_viewer_copies_and_removes_the_snip_it_shows(panel):
    copied, removed = [], []
    panel.copy_requested.connect(copied.append)
    panel.remove_requested.connect(removed.append)
    panel.select("002_snip.png")
    panel.expand()
    viewer = panel.viewer
    viewer.btn_copy.click()
    viewer.btn_remove.click()
    assert copied == ["002_snip.png"]
    assert removed == [["002_snip.png"]]
    viewer.step(1)
    viewer.copy_current()
    assert copied[-1] == "003_snip.png"


def test_the_viewer_right_click_menu(panel):
    panel.expand()
    texts = [text for text, _slot in panel.viewer.context_actions()]
    assert texts == ["Copy", "Remove from lab..."]


def test_the_viewer_says_what_happened_then_shows_the_hints_again(panel, qapp):
    import time

    panel.expand()
    viewer = panel.viewer
    hints = viewer.hint.text()
    viewer.flash("Snip 003 copied", ms=50)
    assert viewer.hint.text() == "Snip 003 copied"
    end = time.monotonic() + 2
    while viewer.hint.text() != hints and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert viewer.hint.text() == hints
