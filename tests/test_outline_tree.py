"""The Outline and Preview tabs of the lab snip panel."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QAbstractItemView, QApplication

import labsnips

Above = QAbstractItemView.DropIndicatorPosition.AboveItem
Below = QAbstractItemView.DropIndicatorPosition.BelowItem
On = QAbstractItemView.DropIndicatorPosition.OnItem


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _snip(file, label, caption="", notes=()):
    return {"kind": "snip", "key": f"snip:{file}", "file": file, "label": label,
            "caption": caption, "notes": list(notes)}


def _note(note_id, text, evidence=()):
    return {"kind": "note", "key": f"note:{note_id}", "id": note_id, "text": text,
            "evidence": list(evidence)}


OUTLINE = {
    "name": "box",
    "record": True,
    "sections": [
        {"path": "", "name": "", "depth": -1, "entries": [_snip("001.png", "001")]},
        {"path": "host", "name": "host", "depth": 0, "entries": []},
        {"path": "host/smb", "name": "smb", "depth": 1, "entries": [
            _snip("002.png", "002", "shares", notes=[_note("n001", "guest ok", ["002.png"])]),
            _note("n002", "loose thought"),
            _snip("003.png", "003"),
        ]},
    ],
}


@pytest.fixture
def tree():
    widget = labsnips.OutlineTree()
    widget.set_outline(OUTLINE)
    widget.show()
    yield widget
    widget.close()


def _item(tree, key):
    return next(i for i in tree._all_items() if i.data(0, labsnips.KEY_ROLE) == key)


def test_the_tree_mirrors_the_report(tree):
    top = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert [t.text(0) for t in top] == ["Top of the report   (1)", "host"]
    smb = top[1].child(0)
    assert smb.text(0) == "smb   (2)"
    assert [smb.child(i).data(0, labsnips.KEY_ROLE) for i in range(smb.childCount())] == [
        "snip:002.png", "note:n002", "snip:003.png",
    ]
    assert smb.child(0).child(0).text(0).endswith("guest ok")
    assert smb.child(0).text(0).startswith("002")


def test_dropping_onto_a_section_files_at_its_end(tree):
    source = _item(tree, "snip:001.png")
    assert tree.resolve_drop(source, _item(tree, "section:host/smb"), On) == (
        "snip:001.png", "host/smb", None,
    )


def test_dropping_above_an_entry_goes_before_it(tree):
    source = _item(tree, "snip:001.png")
    assert tree.resolve_drop(source, _item(tree, "note:n002"), Above) == (
        "snip:001.png", "host/smb", "note:n002",
    )


def test_dropping_below_an_entry_goes_after_it(tree):
    source = _item(tree, "snip:001.png")
    assert tree.resolve_drop(source, _item(tree, "snip:002.png"), Below) == (
        "snip:001.png", "host/smb", "note:n002",
    )
    assert tree.resolve_drop(source, _item(tree, "snip:003.png"), Below) == (
        "snip:001.png", "host/smb", None,
    )


def test_a_note_under_a_snip_stands_for_the_snip(tree):
    source = _item(tree, "snip:001.png")
    assert tree.resolve_drop(source, _item(tree, "note:n001"), Above) == (
        "snip:001.png", "host/smb", "note:n002",
    )


def test_sections_cannot_be_dragged_and_no_op_drops_are_ignored(tree):
    assert tree.resolve_drop(_item(tree, "section:host"), _item(tree, "snip:001.png"), On) is None
    same = _item(tree, "snip:002.png")
    assert tree.resolve_drop(same, same, On) is None
    # Dropping 003 just below 002's neighbour, i.e. where it already is.
    assert tree.resolve_drop(_item(tree, "note:n002"), _item(tree, "snip:002.png"), Below) is None


def test_empty_space_means_the_top_of_the_report(tree):
    assert tree.resolve_drop(_item(tree, "note:n002"), None, On) == ("note:n002", "", None)


def test_a_rebuild_keeps_collapsed_sections_and_the_selection(tree):
    _item(tree, "section:host").setExpanded(False)
    tree.select_key("snip:003.png")
    tree.set_outline(OUTLINE)
    assert not _item(tree, "section:host").isExpanded()
    assert tree.current_key() == "snip:003.png"


def test_clicking_a_snip_or_its_note_names_the_snip(tree):
    got = []
    tree.snip_chosen.connect(got.append)
    tree.itemClicked.emit(_item(tree, "snip:003.png"), 0)
    tree.itemClicked.emit(_item(tree, "note:n001"), 0)
    tree.itemClicked.emit(_item(tree, "section:host"), 0)
    assert got == ["003.png", "002.png"]


def test_the_preview_scales_images_to_fit(tmp_path):
    big = QImage(2400, 1200, QImage.Format.Format_RGB32)
    big.fill(QColor("teal"))
    big.save(str(tmp_path / "001.png"))
    view = labsnips.MarkdownPreview()
    view.resize(420, 500)
    view.show()

    view.show_markdown("# box\n\n![001](001.png)\n", tmp_path)

    loaded = [img for (path, _w), img in view._images.items() if path.endswith("001.png")]
    assert loaded and not loaded[0].isNull()
    assert loaded[0].width() <= 420
    assert "box" in view.toPlainText()
    view.close()


def test_the_panel_has_the_three_tabs():
    panel = labsnips.LabSnipsPanel()
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == [
        "Snips", "Outline", "Preview",
    ]
    moves = []
    panel.move_requested.connect(lambda *a: moves.append(a))
    panel.outline.move_requested.emit("snip:a.png", "s", "")
    assert moves == [("snip:a.png", "s", "")]
    panel.close()


def test_the_preview_tab_gives_the_report_the_full_height():
    panel = labsnips.LabSnipsPanel()
    panel.show()
    panel.tabs.setCurrentIndex(2)
    assert not panel.detail.isVisible()
    panel.tabs.setCurrentIndex(1)
    assert panel.detail.isVisible()
    panel.close()
