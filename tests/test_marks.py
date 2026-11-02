"""Shapes, labels, steps, callouts, spotlight, magnify, the stamp, moving marks and redo (0.11.0)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import annotate as an
import edits


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _image(w=400, h=200, colour="#808080") -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


def P(x, y) -> QPointF:
    return QPointF(x, y)


def _mark(doc, kind, a=(20, 20), b=(120, 80), **extra):
    mark = an.Mark(doc.new_id(), kind, "#e81123", P(*a), P(*b), **extra)
    doc.add(mark)
    return mark


# -- the model ----------------------------------------------------------------------------------
@pytest.mark.parametrize("kind, extra", [
    ("arrow", {}), ("line", {}), ("rect", {}), ("ellipse", {}),
    ("label", {"text": "hello", "size": 16}), ("step", {"number": 1, "size": 16}),
    ("callout", {"text": "look", "size": 16}), ("stamp", {"text": "2026-11-01", "size": 12}),
    ("spotlight", {}), ("magnify", {"c": P(200, 40), "factor": 2.0}),
])
def test_every_mark_changes_the_picture(kind, extra):
    base = _image()
    # Something to magnify and spotlight: a white patch.
    from PySide6.QtGui import QPainter

    p = QPainter(base)
    p.fillRect(QRect(30, 30, 40, 20), QColor("#ffffff"))
    p.end()
    doc = an.AnnotationDoc(base)
    _mark(doc, kind, **extra)
    assert doc.render() != an.AnnotationDoc(base).render()


def test_spotlight_dims_outside_and_keeps_inside():
    doc = an.AnnotationDoc(_image())
    _mark(doc, "spotlight", (100, 50), (300, 150))
    out = doc.render()
    assert QColor(out.pixel(200, 100)) == QColor("#808080")
    assert QColor(out.pixel(10, 10)).lightness() < QColor("#808080").lightness()


def test_two_spotlights_keep_both_areas_bright():
    doc = an.AnnotationDoc(_image())
    _mark(doc, "spotlight", (10, 10), (60, 60))
    _mark(doc, "spotlight", (300, 120), (380, 180))
    out = doc.render()
    assert QColor(out.pixel(30, 30)) == QColor("#808080")
    assert QColor(out.pixel(340, 150)) == QColor("#808080")


def test_marks_made_after_a_spotlight_stay_bright():
    doc = an.AnnotationDoc(_image(colour="#000000"))
    _mark(doc, "spotlight", (300, 150), (390, 190))
    _mark(doc, "rect", (10, 10), (100, 100), width=6)
    assert QColor(doc.render().pixel(10, 50)) == QColor("#e81123")


def test_magnify_shows_the_area_larger():
    base = _image(colour="#000000")
    from PySide6.QtGui import QPainter

    p = QPainter(base)
    p.fillRect(QRect(10, 10, 10, 10), QColor("#00ff00"))
    p.end()
    doc = an.AnnotationDoc(base)
    _mark(doc, "magnify", (10, 10), (20, 20), c=P(200, 50), factor=3.0, width=1)
    out = doc.render()
    assert QColor(out.pixel(215, 65)) == QColor("#00ff00")  # the middle of the 30 px inset


def test_redo_puts_back_what_undo_took():
    doc = an.AnnotationDoc(_image())
    first = _mark(doc, "arrow")
    assert doc.undo() and not doc.ops and doc.can_redo
    assert doc.redo() and doc.ops == [first] and not doc.can_redo
    assert not doc.redo()


def test_something_new_ends_redo():
    doc = an.AnnotationDoc(_image())
    _mark(doc, "arrow")
    doc.undo()
    _mark(doc, "rect")
    assert not doc.can_redo


def test_a_quick_redact_batch_redoes_together():
    doc = an.AnnotationDoc(_image())
    batch = doc.new_id()
    for x in (10, 60, 110):
        doc.add(an.Redact(doc.new_id(), QRect(x, 10, 30, 10), "black", batch))
    doc.undo()
    assert doc.ops == []
    doc.redo()
    assert len(doc.ops) == 3


def test_a_change_moves_a_mark_and_undo_moves_it_back():
    doc = an.AnnotationDoc(_image())
    arrow = _mark(doc, "arrow")
    doc.add(an.Change(doc.new_id(), arrow.id, {"a": P(50, 50), "b": P(150, 150)}))
    assert doc.effective(arrow).a == P(50, 50)
    doc.undo()
    assert doc.effective(arrow).a == P(20, 20)


def test_eraser_and_mark_at_find_marks():
    doc = an.AnnotationDoc(_image())
    line = _mark(doc, "line", (10, 100), (200, 100), width=4)
    box = _mark(doc, "rect", (250, 20), (350, 80), width=2)
    assert doc.hit(P(100, 101), 3) == [line.id]
    assert doc.mark_at(P(250, 50), 3).id == box.id
    assert doc.mark_at(P(300, 50), 3) is None  # inside a box outline is not on it
    label = _mark(doc, "label", (20, 150), (20, 150), text="hi", size=16)
    assert doc.mark_at(P(25, 158), 1).id == label.id


def test_steps_count_up_from_the_highest_showing():
    doc = an.AnnotationDoc(_image())
    assert doc.next_step() == 1
    one = _mark(doc, "step", number=1)
    _mark(doc, "step", number=2)
    assert doc.next_step() == 3
    doc.add(an.Erase(doc.new_id(), frozenset({one.id})))
    assert doc.next_step() == 3


def test_constrain_snaps_lines_and_squares():
    end = an._constrain(P(0, 0), P(100, 8), "line")
    assert abs(end.y()) < 1e-6 and abs(end.x() - (100 ** 2 + 8 ** 2) ** 0.5) < 1e-6
    assert an._constrain(P(0, 0), P(50, -20), "rect") == P(50, -50)


def test_sidecar_keeps_marks_and_changes(tmp_path):
    doc = an.AnnotationDoc(_image())
    arrow = _mark(doc, "arrow", width=3)
    _mark(doc, "callout", text="look here", size=14)
    _mark(doc, "magnify", c=P(250, 20), factor=3.0)
    doc.add(an.Change(doc.new_id(), arrow.id, {"b": P(300, 150), "text": "x"}))
    snip = tmp_path / "s.png"
    data = an._png_of(doc.render())
    snip.write_bytes(data)
    assert edits.save(snip, doc, data)
    back = edits.load(snip)
    assert [type(op).__name__ for op in back.ops] == ["Mark", "Mark", "Mark", "Change"]
    assert back.effective(back.ops[0]).b == P(300, 150)
    assert back.ops[1].text == "look here" and back.ops[2].factor == 3.0
    assert back.render() == doc.render()


def test_sidecar_rejects_unknown_marks(tmp_path):
    with pytest.raises(ValueError):
        edits.op_from_dict({"t": "mark", "id": 1, "kind": "rocket", "color": "#fff", "a": [0, 0], "b": [1, 1]})
    with pytest.raises(ValueError):
        edits.op_from_dict({"t": "change", "id": 2, "target": 1, "fields": {"evil": 1}})


def test_prefs_are_kept_in_range():
    prefs = an.sanitise_prefs({"mark_color": "#0091FF", "shape_kind": "rect", "shape_width": 999,
                               "text_size": 2, "magnify_factor": 7})
    assert prefs["mark_color"] == "#0091ff" and prefs["shape_kind"] == "rect"
    assert prefs["shape_width"] == an.PEN_WIDTHS[1] and prefs["text_size"] == an.TEXT_SIZES[0]
    assert prefs["magnify_factor"] == 2
    assert an.sanitise_prefs({"shape_kind": "star"})["shape_kind"] == "arrow"


# -- the canvas ---------------------------------------------------------------------------------
@pytest.fixture
def canvas():
    widget = an.AnnotCanvas()
    widget.resize(420, 220)
    widget.show()
    widget.load(_image())
    QApplication.processEvents()
    yield widget
    widget.close()


def W(canvas, x, y) -> QPoint:
    return canvas.to_widget(P(x, y)).toPoint()


def _drag(canvas, a, b, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifiers, W(canvas, *a))
    for i in range(1, 5):
        x = a[0] + (b[0] - a[0]) * i / 4
        y = a[1] + (b[1] - a[1]) * i / 4
        QTest.mouseMove(canvas, W(canvas, x, y))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifiers, W(canvas, *b))


def _marks(canvas):
    return canvas.doc.marks()


def test_shape_tool_draws_the_chosen_shape(canvas):
    canvas.prefs["shape_kind"] = "ellipse"
    canvas.prefs["mark_color"] = "#0091ff"
    canvas.set_tool("shape")
    _drag(canvas, (40, 40), (160, 120))
    (mark,) = _marks(canvas)
    assert mark.kind == "ellipse" and mark.color == "#0091ff"
    assert abs(mark.b.x() - 160) <= 2 and abs(mark.b.y() - 120) <= 2


def test_a_tiny_drag_draws_nothing(canvas):
    canvas.set_tool("shape")
    _drag(canvas, (40, 40), (41, 40))
    assert _marks(canvas) == []


def test_shift_keeps_an_arrow_straight(canvas):
    canvas.prefs["shape_kind"] = "arrow"
    canvas.set_tool("shape")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 40, 100))
    QTest.mouseMove(canvas, W(canvas, 200, 108))
    from PySide6.QtGui import QMouseEvent

    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(W(canvas, 220, 110)), QPointF(),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
    canvas.mouseMoveEvent(move)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, W(canvas, 220, 110))
    (mark,) = _marks(canvas)
    assert abs(mark.b.y() - mark.a.y()) < 1.0


def test_steps_number_themselves(canvas):
    canvas.set_tool("step")
    for x in (40, 120, 200):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, x, 60))
    assert [m.number for m in _marks(canvas)] == [1, 2, 3]


def test_label_is_typed_in_place(canvas):
    canvas.set_tool("label")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    assert canvas.editing_text()
    QTest.keyClicks(canvas._editor, "port 445")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    (mark,) = _marks(canvas)
    assert mark.kind == "label" and mark.text == "port 445"
    assert not canvas.editing_text()


def test_esc_drops_the_label(canvas):
    canvas.set_tool("label")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    QTest.keyClicks(canvas._editor, "nope")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Escape)
    assert _marks(canvas) == [] and not canvas.editing_text()


def test_a_label_near_the_edge_is_kept_on_the_snip(canvas):
    canvas.set_tool("label")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 390, 190))
    QTest.keyClicks(canvas._editor, "a long label that would not fit")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    (mark,) = _marks(canvas)
    box = an.text_box(mark)
    assert box.right() <= 400.5 and box.bottom() <= 200.5


def test_callout_is_an_arrow_and_words(canvas):
    canvas.set_tool("callout")
    _drag(canvas, (60, 150), (200, 40))
    QTest.keyClicks(canvas._editor, "null session")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    (mark,) = _marks(canvas)
    assert mark.kind == "callout" and mark.text == "null session"
    assert abs(mark.a.x() - 60) <= 2 and abs(mark.a.y() - 150) <= 2


def test_magnify_places_its_copy_inside_the_snip(canvas):
    canvas.prefs["magnify_factor"] = 2
    canvas.set_tool("magnify")
    _drag(canvas, (20, 20), (80, 40))
    (mark,) = _marks(canvas)
    _source, inset = an.magnify_rects(mark)
    assert mark.factor == 2 and P(0, 0).x() <= inset.left() and inset.right() <= 400.5


def test_select_moves_a_mark_and_undo_puts_it_back(canvas):
    canvas.prefs["shape_kind"] = "rect"
    canvas.set_tool("shape")
    _drag(canvas, (40, 40), (140, 100))
    canvas.set_tool("select")
    _drag(canvas, (40, 70), (90, 120))  # grab the left edge, move it 50 right and down
    (mark,) = _marks(canvas)
    assert abs(mark.a.x() - 90) <= 2 and abs(mark.a.y() - 90) <= 2
    canvas.undo()
    (mark,) = _marks(canvas)
    assert abs(mark.a.x() - 40) <= 2
    canvas.redo()
    assert abs(_marks(canvas)[0].a.x() - 90) <= 2


def test_select_resizes_by_a_handle(canvas):
    canvas.prefs["shape_kind"] = "arrow"
    canvas.set_tool("shape")
    _drag(canvas, (40, 40), (140, 100))
    canvas.set_tool("select")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 90, 70))
    assert canvas.selected_mark() is not None
    _drag(canvas, (140, 100), (300, 150))
    (mark,) = _marks(canvas)
    assert abs(mark.b.x() - 300) <= 2 and abs(mark.a.x() - 40) <= 2


def test_clicking_empty_space_deselects(canvas):
    canvas.set_tool("step")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    canvas.set_tool("select")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    assert canvas.selected_mark() is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 300, 150))
    assert canvas.selected_mark() is None


def test_delete_removes_the_selected_mark_only_with_select(canvas):
    canvas.set_tool("step")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    assert canvas.delete_selected() is False
    canvas.set_tool("select")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    assert canvas.delete_selected() is True
    assert _marks(canvas) == []
    canvas.undo()
    assert len(_marks(canvas)) == 1


def test_double_click_retypes_and_emptying_deletes(canvas):
    canvas.set_tool("label")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    QTest.keyClicks(canvas._editor, "old")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    canvas.set_tool("select")
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 55, 58))
    assert canvas.editing_text() and canvas._editor.text() == "old"
    canvas._editor.setText("new")
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    assert _marks(canvas)[0].text == "new"
    canvas.edit_text(_marks(canvas)[0])
    canvas._editor.clear()
    QTest.keyClick(canvas._editor, Qt.Key.Key_Return)
    assert _marks(canvas) == []


def test_right_click_on_a_mark_offers_edit_and_delete(canvas):
    doc = canvas.doc
    _mark(doc, "label", (50, 50), (50, 50), text="hi", size=16)
    canvas._refresh()
    labels = [row[0] for row in canvas.context_actions(QPointF(W(canvas, 55, 58))) if row]
    assert labels[:2] == ["Edit text...", "Delete this mark"]


def test_stamp_goes_bottom_right_with_the_snips_time(canvas, monkeypatch):
    import socket

    # Pinned: build machines have long names (fv-az1234-567) that push the
    # stamp further left, which is right, but not what this test measures.
    monkeypatch.setattr(socket, "gethostname", lambda: "KALI")
    canvas.stamp_time = "2026-10-31 18:20:10"
    canvas.add_stamp()
    (mark,) = _marks(canvas)
    box = an.text_box(mark)
    assert mark.text == "2026-10-31 18:20:10  |  KALI"
    assert box.right() <= 400 and box.bottom() <= 200 and box.left() > 200


def test_a_long_machine_name_still_keeps_the_stamp_on_the_snip(canvas, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: "fv-az1234-567-a-very-long-runner-name")
    canvas.add_stamp()
    (mark,) = _marks(canvas)
    box = an.text_box(mark)
    assert box.left() >= 0 and box.top() >= 0 and box.bottom() <= 200


def test_redo_signal_follows_the_history(canvas):
    seen = []
    canvas.redo_changed.connect(seen.append)
    canvas.set_tool("step")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 50, 50))
    canvas.undo()
    assert seen[-1] is True
    canvas.redo()
    assert seen[-1] is False


def test_pen_with_shift_draws_a_straight_line(canvas):
    canvas.set_tool("pen")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, W(canvas, 40, 40))
    from PySide6.QtGui import QMouseEvent

    for x, y in ((80, 60), (120, 45), (200, 44)):
        canvas.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(W(canvas, x, y)), QPointF(),
                                          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.ShiftModifier))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, W(canvas, 200, 44))
    (stroke,) = [op for op in canvas.doc.ops if isinstance(op, an.Stroke)]
    assert len(stroke.points) == 2


# -- the tool strip ---------------------------------------------------------------------------------
@pytest.fixture
def strip():
    widget = an.AnnotToolbar()
    widget.show()
    yield widget
    for popup in (widget.pen_popup, widget.hl_popup, widget.redact_popup, *widget.mark_popups.values()):
        popup.hide()
    widget.close()


def test_strip_has_every_new_tool(strip):
    for kind in ("select", "shape", "label", "step", "callout", "spotlight", "magnify"):
        assert kind in strip.buttons
    assert strip.btn_redo is not None and strip.btn_stamp is not None


def test_redo_and_stamp_buttons_signal(strip):
    got = []
    strip.redo_requested.connect(lambda: got.append("redo"))
    strip.stamp_requested.connect(lambda: got.append("stamp"))
    strip.set_redo_enabled(True)
    strip.btn_redo.click()
    strip.btn_stamp.click()
    assert got == ["redo", "stamp"]
    strip.set_available(False)
    assert not strip.btn_redo.isEnabled() and not strip.btn_stamp.isEnabled()


def test_shape_popup_changes_the_shape_and_colour(strip):
    changed = []
    strip.prefs_changed.connect(changed.append)
    popup = strip.mark_popups["shape"]
    popup.set_prefs(strip.prefs)
    popup.choices["rect"].click()
    blue = next(s for s in popup.swatches if s.color == "#0091ff")
    blue.click()
    assert changed[-1]["shape_kind"] == "rect" and changed[-1]["mark_color"] == "#0091ff"


def test_strip_still_fits_a_small_window(strip):
    # About 600 px on Linux; Windows draws buttons a little wider. The point
    # is that the strip does not grow back towards 0.11's first, looser 690.
    assert strip.minimumSizeHint().width() <= 760
