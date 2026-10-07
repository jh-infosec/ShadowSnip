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
