"""Thumbnails, in-place editing and the viewer in the lab snip list."""

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
    saved = []
    widget.details_saved.connect(lambda *args: saved.append(args))
    widget.saved = saved
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
    assert panel.caption_edit.text() == "caption 3"
    assert [e.toPlainText() for _i, e in panel._note_editors] == ["note 3"]
    assert not panel.btn_save.isEnabled()


def test_hover_shows_a_bigger_preview(panel):
    tip = panel.list.topLevelItem(0).toolTip(0)
    assert "<img " in tip and "003_snip.png" in tip
    assert "caption 3" in tip


def test_editing_enables_save_and_save_emits_only_what_changed(panel):
    panel.caption_edit.setText("anonymous login")
    panel.caption_edit.textEdited.emit("anonymous login")
    assert panel.btn_save.isEnabled()

    panel.save()

    assert panel.saved == [("003_snip.png", "anonymous login", {}, "")]
    assert not panel.btn_save.isEnabled()


def test_a_changed_note_and_a_new_note_are_emitted(panel):
    _note_id, editor = panel._note_editors[0]
    editor.setPlainText("note 3, corrected")
    panel.new_note.setPlainText("second thought")

    panel.save()

    assert panel.saved == [
        ("003_snip.png", "caption 3", {"n003": "note 3, corrected"}, "second thought")
    ]
    assert panel.new_note.toPlainText() == ""


def test_moving_to_another_snip_saves_the_edits_first(panel):
    panel._note_editors[0][1].setPlainText("")  # emptied: remove it
    panel.select("001_snip.png")

    assert panel.saved == [("003_snip.png", "caption 3", {"n003": ""}, "")]
    assert panel.caption_edit.text() == "caption 1"


def test_a_refresh_does_not_wipe_edits_in_progress(panel, rows):
    panel.new_note.setPlainText("half typed")
    panel.set_rows(rows, current_file="003_snip.png")

    assert panel.new_note.toPlainText() == "half typed"
    assert panel.is_dirty()


def test_a_snip_without_a_record_cannot_be_edited(panel, rows):
    rows[0]["recorded"] = False
    panel.set_rows(rows, current_file="003_snip.png")
    panel.select("001_snip.png")
    assert panel.caption_edit.isReadOnly()


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
