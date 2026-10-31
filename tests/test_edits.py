"""Marks stay editable after you leave a snip (0.10.0): edits.py and its use."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import annotate as an
import config
import edits
import lab
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _image(colour="#336699", w=200, h=120) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


def _doc_with_marks() -> an.AnnotationDoc:
    doc = an.AnnotationDoc(_image())
    doc.add(an.Stroke(doc.new_id(), "pen", "#e81123", 4.0, [QPointF(10, 10), QPointF(80, 40)]))
    doc.add(an.Stroke(doc.new_id(), "highlighter", "#fff100", 18.0, [QPointF(20, 90), QPointF(150, 90)]))
    doc.add(an.Redact(doc.new_id(), QRect(100, 10, 60, 30), "black"))
    doc.add(an.Restyle(doc.new_id(), 3, "blur"))
    doc.add(an.Crop(doc.new_id(), QRect(5, 5, 180, 100)))
    doc.add(an.Erase(doc.new_id(), frozenset({1})))
    return doc


def _write_snip(path: Path, doc: an.AnnotationDoc) -> bytes:
    """Write the flattened snip as the app does, and return its bytes."""
    import imageops

    result = imageops.process(doc.render(), config._sanitise(dict(config.DEFAULTS)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.disk.data)
    return result.disk.data


# -- the store --------------------------------------------------------------------------------
def test_marks_round_trip_exactly(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    data = _write_snip(snip, doc)
    assert edits.save(snip, doc, data)
    back = edits.load(snip)
    assert [edits.op_to_dict(op) for op in back.ops] == [edits.op_to_dict(op) for op in doc.ops]
    assert back.base.size() == doc.base.size()
    assert back._next == doc._next
    assert back.render() == doc.render()  # the same picture, rebuilt from the marks


def test_every_mark_can_be_erased_or_undone_after_reopening(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    back = edits.load(snip)
    # The redaction is a separate mark again: hit-testable, erasable, undoable.
    assert back.redaction_at(QPointF(120, 20)) is not None
    redact = back.redaction_at(QPointF(120, 20))
    back.add(an.Erase(back.new_id(), frozenset({redact.id})))
    assert back.redaction_at(QPointF(120, 20)) is None
    while back.undo():
        pass
    assert back.render() == back.base.convertToFormat(QImage.Format.Format_RGB32)


def test_the_sidecar_is_hidden_beside_the_snip(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    names = sorted(p.name for p in (tmp_path / ".edits").iterdir())
    assert names == ["001_a.png.json", "001_a.png.orig.png"]
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["001_a.png"]


def test_a_snip_changed_outside_shadowsnip_opens_as_it_is(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    _image("#ff0000").save(str(snip))  # edited in Paint, say
    assert edits.load(snip) is None


def test_no_marks_means_no_sidecar(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    empty = an.AnnotationDoc(_image())
    assert edits.save(snip, empty, b"x") is False
    assert not (tmp_path / ".edits" / "001_a.png.json").exists()
    assert not (tmp_path / ".edits" / "001_a.png.orig.png").exists()


@pytest.mark.parametrize("damage", [
    lambda r: r.update(version=99),
    lambda r: r.update(file="other.png"),
    lambda r: r.update(ops=[{"t": "nuke", "id": 1}]),
    lambda r: r.update(ops=[{"t": "redact", "id": 1, "rect": [0, 0, -5, 3], "mode": "black"}]),
    lambda r: r.update(ops=[{"t": "stroke", "id": 1, "kind": "pen", "color": "#000", "width": 2, "points": []}]),
    lambda r: r.update(ops="not a list"),
])
def test_a_damaged_record_is_ignored_not_trusted(tmp_path, damage):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    record_path = tmp_path / ".edits" / "001_a.png.json"
    record = json.loads(record_path.read_text())
    damage(record)
    record_path.write_text(json.dumps(record))
    assert edits.load(snip) is None


def test_switched_off_nothing_is_written_or_read(tmp_path):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    data = _write_snip(snip, doc)
    edits.save(snip, doc, data)
    edits.enabled = False
    assert edits.load(snip) is None
    other = tmp_path / "002_b.png"
    assert edits.save(other, doc, _write_snip(other, doc)) is False
    assert not (tmp_path / ".edits" / "002_b.png.json").exists()


def test_the_original_is_written_once_per_place(tmp_path, monkeypatch):
    doc = _doc_with_marks()
    snip = tmp_path / "001_a.png"
    data = _write_snip(snip, doc)
    writes = []
    real = storage.write_atomic
    monkeypatch.setattr(storage, "write_atomic", lambda p, d: writes.append(Path(p).name) or real(p, d))
    edits.save(snip, doc, data)
    edits.save(snip, doc, data)
    assert writes.count("001_a.png.orig.png") == 1
    assert writes.count("001_a.png.json") == 2


def test_move_and_prune_and_delete_all(tmp_path):
    doc = _doc_with_marks()
    a, b = tmp_path / "001_a.png", tmp_path / "002_b.png"
    edits.save(a, doc, _write_snip(a, doc))
    edits.save(b, doc.clone(), _write_snip(b, doc))
    moved = tmp_path / "removed" / "001_a.png"
    moved.parent.mkdir()
    a.replace(moved)
    edits.move(a, moved)
    assert not (tmp_path / ".edits" / "001_a.png.json").exists()
    assert edits.load(moved) is not None  # still editable where it went
    assert edits.prune(tmp_path, keep_names=[]) == 2  # b's two files
    assert edits.delete_all([tmp_path]) == 2  # what moved with a
    assert not list(tmp_path.rglob(".edits/*"))


# -- in the lab and the history folder ----------------------------------------------------------
@pytest.fixture
def cfg_lab(cfg):
    lab.start(cfg, "box")
    cfg["active_lab"] = "box"
    return cfg


def test_removing_a_lab_snip_takes_its_marks_along(cfg_lab):
    doc = _doc_with_marks()
    path = lab.save(b"", "png", cfg_lab)
    edits.save(path, doc, _write_snip(path, doc))
    lab.remove_snip(cfg_lab, path.name)
    folder = lab.active_folder(cfg_lab)
    assert not (folder / ".edits" / f"{path.name}.json").exists()
    assert edits.load(folder / lab.REMOVED_DIR / path.name) is not None


def test_history_pruning_and_removal_clean_up(cfg):
    cfg["keep_history"] = True
    cfg["history_limit"] = 1
    doc = _doc_with_marks()
    first = storage.save_history(b"x", "png", cfg)
    edits.save(first, doc, _write_snip(first, doc))
    import time

    time.sleep(0.02)
    second = storage.save_history(b"y", "png", cfg)  # prunes the first
    assert not first.exists()
    assert not (first.parent / ".edits" / f"{first.name}.json").exists()
    assert not (first.parent / ".edits" / f"{first.name}.orig.png").exists()
    edits.save(second, doc, _write_snip(second, doc))
    moved = storage.remove_from_history(cfg, second.name)
    assert edits.load(moved) is not None


def test_the_lab_and_history_lists_never_show_the_sidecars(cfg_lab, cfg):
    doc = _doc_with_marks()
    path = lab.save(b"", "png", cfg_lab)
    edits.save(path, doc, _write_snip(path, doc))
    assert [r["file"] for r in lab.snip_rows(cfg_lab)] == [path.name]


# -- the journey from the request: draw, snip again, come back, erase ---------------------------
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


def _draw(canvas, doc_points=((20, 20), (150, 80))):
    doc = canvas.doc
    doc.add(an.Stroke(doc.new_id(), "pen", "#e81123", 5.0, [QPointF(*p) for p in doc_points]))
    canvas._refresh()
    canvas.edited.emit()


def test_marks_on_an_earlier_snip_can_be_erased_after_another_snip(shadow):
    shadow._handle_snip(_image("#224466", 300, 160))
    first = shadow._snip_paths["history"]
    _draw(shadow.preview.canvas)
    shadow.preview.canvas.doc.add(an.Redact(shadow.preview.canvas.doc.new_id(), QRect(200, 20, 60, 40), "black"))
    shadow.preview.canvas.edited.emit()
    shadow.preview.flush_edits()
    marked = QImage(str(first))

    shadow._handle_snip(_image("#664422", 300, 160))  # a new snip: the old way set it in stone
    assert shadow._snip_paths["history"] != first

    # Come back to the first snip in the full-size view.
    panel = shadow.preview.snips_panel
    panel.select(first.name)
    panel.expand()
    viewer = panel.viewer
    assert viewer.current_file() == first.name
    doc = viewer.canvas.doc
    assert [type(op).__name__ for op in doc.ops] == ["Stroke", "Redact"]
    assert viewer.canvas.doc.can_undo

    # Erase the redaction, as the eraser would, and let it save.
    redaction = doc.redaction_at(QPointF(220, 40))
    doc.add(an.Erase(doc.new_id(), frozenset({redaction.id})))
    viewer.canvas._refresh()
    viewer.canvas.edited.emit()
    viewer.flush_edits()

    unmarked = QImage(str(first))
    assert unmarked.pixelColor(230, 40) != marked.pixelColor(230, 40)  # redaction gone from the file
    viewer.close()

    # And again later: the stroke is still its own mark, the redaction stays erased.
    again = edits.load(first)
    assert [type(op).__name__ for op in again.ops] == ["Stroke", "Redact", "Erase"]
    assert again.redaction_at(QPointF(220, 40)) is None


def test_editing_the_on_screen_snip_in_the_viewer_keeps_marks_in_the_window(shadow):
    shadow._handle_snip(_image("#224466", 300, 160))
    _draw(shadow.preview.canvas)
    shadow.preview.flush_edits()
    panel = shadow.preview.snips_panel
    panel.expand()
    viewer = panel.viewer
    doc = viewer.canvas.doc
    doc.add(an.Stroke(doc.new_id(), "highlighter", "#fff100", 12.0, [QPointF(10, 140), QPointF(290, 140)]))
    viewer.canvas._refresh()
    viewer.canvas.edited.emit()
    viewer.flush_edits()
    window_doc = shadow.preview.canvas.doc
    assert [op.kind for op in window_doc.ops] == ["pen", "highlighter"]  # both still marks
    assert window_doc is not doc  # its own copy: undo in one does not reach the other
    viewer.close()


def test_with_keep_edits_off_a_new_snip_still_sets_marks_in_stone(shadow):
    edits.enabled = False
    shadow._handle_snip(_image("#224466", 300, 160))
    first = shadow._snip_paths["history"]
    _draw(shadow.preview.canvas)
    shadow.preview.flush_edits()
    assert not (first.parent / ".edits").exists()


def test_settings_offers_the_switch_and_the_delete(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from settings_dialog import SettingsDialog

    cfg = config._sanitise({**config.DEFAULTS, "save_dir": str(tmp_path / "snips")})
    doc = _doc_with_marks()
    snip = storage.history_folder(cfg) / "snip_1.png"
    edits.save(snip, doc, _write_snip(snip, doc))
    dialog = SettingsDialog(cfg)
    assert dialog.keep_edits_check.isChecked()
    dialog.keep_edits_check.setChecked(False)
    assert dialog.values()["keep_edits"] is False
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.btn_forget_edits.click()
    assert not list(storage.history_folder(cfg).rglob(".edits/*"))
    assert snip.exists()  # the snip itself is untouched
