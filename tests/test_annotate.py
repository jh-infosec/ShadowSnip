"""Marking up a snip: the operations, the canvas gestures, the tool strip."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import annotate as an


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _image(w=200, h=100, color="#ffffff"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def _striped(w=200, h=100):
    """White with a dotted black line across the middle: detail a blur must lose."""
    img = _image(w, h)
    for x in range(0, w, 2):
        for y in range(45, 55):
            img.setPixelColor(x, y, QColor("#000000"))
    return img


def _px(img, x, y):
    return img.pixelColor(x, y).name()


# -- the document ------------------------------------------------------------------
def test_no_marks_means_the_original():
    doc = an.AnnotationDoc(_image())
    assert not doc.edited and not doc.can_undo
    out = doc.render()
    assert out.size() == doc.base.size() and _px(out, 5, 5) == "#ffffff"


def test_the_pen_draws_in_its_colour():
    doc = an.AnnotationDoc(_image())
    doc.add(an.Stroke(doc.new_id(), "pen", "#e81123", 4, [QPointF(10, 10), QPointF(90, 10)]))
    assert _px(doc.render(), 50, 10) == "#e81123"


def test_the_highlighter_is_see_through():
    doc = an.AnnotationDoc(_image(color="#000000"))
    doc.add(an.Stroke(doc.new_id(), "highlighter", "#fff100", 10, [QPointF(10, 30), QPointF(90, 30)]))
    tinted = doc.render().pixelColor(50, 30)
    # Not the solid colour, not the black under it: a mix.
    assert 0 < tinted.red() < 255 and tinted.name() != "#fff100"


def test_black_out_leaves_nothing_of_the_original():
    doc = an.AnnotationDoc(_striped())
    doc.add(an.Redact(doc.new_id(), QRect(20, 40, 100, 20), "black"))
    out = doc.render()
    assert {_px(out, x, y) for x in range(20, 120) for y in range(40, 60)} == {"#000000"}
    assert _px(out, 150, 50) in ("#000000", "#ffffff")  # outside untouched


def test_blur_destroys_the_detail():
    doc = an.AnnotationDoc(_striped())
    doc.add(an.Redact(doc.new_id(), QRect(20, 40, 100, 20), "blur"))
    out = doc.render()
    row = [out.pixelColor(x, 50).lightness() for x in range(30, 110)]
    # The alternating black and white is gone: neighbours are nearly equal.
    assert max(abs(a - b) for a, b in zip(row, row[1:])) < 20


def test_a_blur_covers_strokes_drawn_before_it():
    doc = an.AnnotationDoc(_image())
    doc.add(an.Stroke(doc.new_id(), "pen", "#000000", 6, [QPointF(30, 50), QPointF(110, 50)]))
    doc.add(an.Redact(doc.new_id(), QRect(20, 40, 100, 20), "black"))
    assert _px(doc.render(), 70, 50) == "#000000"


def test_crop_keeps_the_area():
    doc = an.AnnotationDoc(_image(200, 100))
    doc.add(an.Crop(doc.new_id(), QRect(50, 20, 80, 40)))
    assert doc.render().size().toTuple() == (80, 40)
    assert doc.crop_rect() == QRect(50, 20, 80, 40)


def test_the_eraser_hides_a_mark_and_undo_brings_it_back():
    doc = an.AnnotationDoc(_image())
    doc.add(an.Stroke(doc.new_id(), "pen", "#e81123", 4, [QPointF(10, 10), QPointF(90, 10)]))
    hits = doc.hit(QPointF(50, 12), 3)
    assert hits
    doc.add(an.Erase(doc.new_id(), frozenset(hits)))
    assert _px(doc.render(), 50, 10) == "#ffffff"
    doc.undo()
    assert _px(doc.render(), 50, 10) == "#e81123"


def test_the_eraser_reaches_redaction_boxes_and_misses_empty_space():
    doc = an.AnnotationDoc(_image())
    box = an.Redact(doc.new_id(), QRect(100, 40, 40, 20), "black")
    doc.add(box)
    assert doc.hit(QPointF(120, 50), 2) == [box.id]
    assert doc.hit(QPointF(10, 90), 2) == []


def test_undo_walks_back_one_operation_at_a_time():
    doc = an.AnnotationDoc(_image())
    doc.add(an.Stroke(doc.new_id(), "pen", "#000000", 2, [QPointF(1, 1)]))
    doc.add(an.Crop(doc.new_id(), QRect(0, 0, 50, 50)))
    assert doc.undo() and doc.render().width() == 200
    assert doc.undo() and not doc.can_undo
    assert doc.undo() is False


# -- the canvas ---------------------------------------------------------------------
@pytest.fixture
def canvas():
    widget = an.AnnotCanvas()
    widget.resize(420, 220)
    widget.show()
    widget.load(_image(400, 200))
    QApplication.processEvents()
    yield widget
    widget.close()


def _drag(widget, a, b, steps=6):
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, steps + 1):
        point = QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps)
        QTest.mouseMove(widget, point)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def test_without_a_tool_a_drag_does_nothing(canvas):
    edits = []
    canvas.edited.connect(lambda: edits.append(1))
    _drag(canvas, QPoint(50, 50), QPoint(150, 100))
    assert edits == [] and not canvas.doc.edited


def test_a_pen_drag_becomes_a_stroke(canvas):
    edits = []
    canvas.edited.connect(lambda: edits.append(1))
    canvas.set_tool("pen")
    _drag(canvas, QPoint(50, 50), QPoint(150, 50))
    assert edits == [1]
    stroke = canvas.doc.ops[0]
    assert isinstance(stroke, an.Stroke) and stroke.kind == "pen" and len(stroke.points) > 2


def test_stroke_widths_follow_the_screen_size(canvas):
    canvas.prefs["pen_width"] = 6
    canvas.set_tool("pen")
    _drag(canvas, QPoint(50, 50), QPoint(150, 50))
    # The image is shown at its own size here, so 6 screen px is 6 image px.
    assert canvas.doc.ops[0].width == pytest.approx(6 / canvas.scale())


def test_a_crop_drag_crops_and_maps_to_image_pixels(canvas):
    canvas.set_tool("crop")
    _drag(canvas, QPoint(60, 40), QPoint(160, 140))
    crop = canvas.doc.crop_rect()
    assert crop.width() == pytest.approx(100, abs=3) and crop.height() == pytest.approx(100, abs=3)
    # After a crop, a point maps back into the original's coordinates.
    centre = canvas.to_widget(QPointF(crop.center()))
    assert canvas.to_image(centre).x() == pytest.approx(crop.center().x(), abs=1)


def test_a_click_is_not_a_crop_or_a_redaction(canvas):
    canvas.set_tool("redact")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(80, 80))
    assert not canvas.doc.edited


def test_a_redact_drag_uses_the_chosen_mode(canvas):
    canvas.prefs["redact_mode"] = "blur"
    canvas.set_tool("redact")
    _drag(canvas, QPoint(40, 40), QPoint(120, 90))
    assert canvas.doc.ops[0].mode == "blur"


def test_the_eraser_drag_removes_what_it_crosses_as_one_step(canvas):
    canvas.set_tool("pen")
    _drag(canvas, QPoint(40, 60), QPoint(200, 60))
    _drag(canvas, QPoint(40, 120), QPoint(200, 120))
    canvas.set_tool("eraser")
    _drag(canvas, QPoint(100, 40), QPoint(100, 140))
    erase = canvas.doc.ops[-1]
    assert isinstance(erase, an.Erase) and len(erase.targets) == 2
    canvas.undo()
    assert not any(isinstance(op, an.Erase) for op in canvas.doc.ops)


def test_undo_reports_and_announces(canvas):
    states, edits = [], []
    canvas.undo_changed.connect(states.append)
    canvas.edited.connect(lambda: edits.append(1))
    canvas.set_tool("pen")
    _drag(canvas, QPoint(40, 60), QPoint(200, 60))
    canvas.undo()
    assert states == [True, False] and edits == [1, 1]


def test_loading_a_new_snip_starts_clean(canvas):
    canvas.set_tool("pen")
    _drag(canvas, QPoint(40, 60), QPoint(200, 60))
    canvas.load(_image(100, 100))
    assert not canvas.doc.edited


# -- the tool strip ---------------------------------------------------------------------
@pytest.fixture
def strip():
    widget = an.AnnotToolbar()
    widget.show()
    yield widget
    widget.pen_popup.hide()
    widget.hl_popup.hide()
    widget.redact_popup.hide()
    widget.close()


def test_click_selects_click_again_opens_options(strip):
    tools = []
    strip.tool_changed.connect(tools.append)
    strip.buttons["pen"].click()
    assert tools == ["pen"] and strip.buttons["pen"].isChecked()
    strip.buttons["pen"].click()
    assert strip.pen_popup.isVisible()


def test_the_eraser_and_crop_put_down_on_a_second_click(strip):
    strip.buttons["eraser"].click()
    strip.buttons["eraser"].click()
    assert strip.tool is None and not strip.buttons["eraser"].isChecked()


def test_picking_a_colour_and_width_updates_the_prefs(strip):
    seen = []
    strip.prefs_changed.connect(seen.append)
    strip.open_options("highlighter")
    popup = strip.hl_popup
    popup.slider.setValue(30)
    green = next(s for s in popup.swatches if s.color == "#16e01c")
    green.click()
    assert seen[-1]["highlighter_color"] == "#16e01c"
    assert seen[-1]["highlighter_width"] == 30


def test_the_pen_has_a_full_palette_and_the_highlighter_a_short_one(strip):
    assert len(strip.pen_popup.swatches) == 30
    assert len(strip.hl_popup.swatches) == 6


def test_redact_mode_is_chosen_in_its_popup(strip):
    seen = []
    strip.prefs_changed.connect(seen.append)
    strip.open_options("redact")
    strip.redact_popup.blur.click()
    assert seen[-1]["redact_mode"] == "blur" and not strip.redact_popup.isVisible()


def test_undo_button_follows_the_canvas(strip):
    assert not strip.btn_undo.isEnabled()
    strip.set_undo_enabled(True)
    assert strip.btn_undo.isEnabled()


@pytest.mark.parametrize(
    "stored,expected",
    [
        (None, an.DEFAULT_PREFS),
        ({"pen_width": 999}, {**an.DEFAULT_PREFS, "pen_width": an.PEN_WIDTHS[1]}),
        ({"pen_color": "#123456"}, an.DEFAULT_PREFS),
        ({"redact_mode": "blur", "highlighter_width": "20"},
         {**an.DEFAULT_PREFS, "redact_mode": "blur", "highlighter_width": 20}),
    ],
)
def test_stored_prefs_are_checked(stored, expected):
    assert an.sanitise_prefs(stored) == expected
