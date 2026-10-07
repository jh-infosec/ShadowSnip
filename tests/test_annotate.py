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


def test_left_click_picks_up_and_puts_down(strip):
    tools = []
    strip.tool_changed.connect(tools.append)
    strip.buttons["redact"].click()
    assert tools == ["redact"] and strip.buttons["redact"].isChecked()
    strip.buttons["redact"].click()
    assert tools == ["redact", None] and not strip.buttons["redact"].isChecked()
    assert not strip.redact_popup.isVisible()


def test_one_tool_at_a_time(strip):
    strip.buttons["pen"].click()
    strip.buttons["crop"].click()
    assert [k for k, b in strip.buttons.items() if b.isChecked()] == ["crop"]


def test_right_click_opens_the_options_and_picks_the_tool_up(strip):
    strip._on_tool_right_clicked("pen")
    assert strip.tool == "pen" and strip.pen_popup.isVisible()
    strip.pen_popup.hide()
    strip._on_tool_right_clicked("redact")
    assert strip.tool == "redact" and strip.redact_popup.isVisible()


def test_right_click_on_a_tool_without_options_opens_nothing(strip):
    strip._on_tool_right_clicked("eraser")
    assert strip.tool == "eraser"
    assert not any(p.isVisible() for p in (strip.pen_popup, strip.hl_popup, strip.redact_popup))


def test_left_click_closes_an_open_options_popup(strip):
    strip._on_tool_right_clicked("pen")
    strip.buttons["pen"].click()
    assert strip.tool is None and not strip.pen_popup.isVisible()


def test_hover_explains_the_tool(strip):
    from PySide6.QtCore import QEvent

    tip = strip.buttons["redact"].toolTip()
    assert "Redact" in tip and "Right-click: blur or black out" in tip
    assert "Right-click" not in strip.buttons["eraser"].toolTip()
    QApplication.sendEvent(strip.buttons["highlighter"], QEvent(QEvent.Type.Enter))
    assert strip.hint.text().startswith("Highlighter:")
    QApplication.sendEvent(strip.buttons["highlighter"], QEvent(QEvent.Type.Leave))
    assert not strip.hint.text().startswith("Highlighter:")


def test_without_a_snip_the_tools_are_shown_but_unusable(strip):
    strip.buttons["pen"].click()
    strip.set_available(False)
    assert strip.isVisible()
    assert not any(b.isEnabled() for b in strip.buttons.values())
    assert strip.tool is None and strip.hint.text() == an.NO_SNIP_HINT
    strip.set_available(True)
    assert all(b.isEnabled() for b in strip.buttons.values())


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


def test_pen_colours_run_light_to_dark_in_each_family_row():
    rows = [an.PEN_COLORS[i:i + an.PEN_COLUMNS] for i in range(0, len(an.PEN_COLORS), an.PEN_COLUMNS)]
    assert len(rows) == 6
    for row in rows:
        lightness = [QColor(c).lightness() for c in row]
        assert lightness == sorted(lightness, reverse=True), row


def test_each_pen_row_is_one_colour_family():
    rows = [an.PEN_COLORS[i:i + an.PEN_COLUMNS] for i in range(0, len(an.PEN_COLORS), an.PEN_COLUMNS)]
    for row in rows[1:]:  # the greys have no hue
        hues = [QColor(c).hslHue() for c in row]
        spread = max(hues) - min(hues)
        assert min(spread, 360 - spread) <= 45, row


def test_highlighters_are_in_spectrum_order():
    hues = [QColor(c).hslHue() for c in an.HIGHLIGHTER_COLORS]
    # yellow, orange, pink, purple, blue, green: round the colour wheel one way
    assert hues[0] > hues[1] and hues[2] > hues[3] > hues[4] > hues[5]


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



# -- the tool drawn on the snip ----------------------------------------------------------
def _point_at(canvas, point):
    """Put the pointer over `point` for a drawing check, without a mouse event.

    The drawing tests check what is painted, not how the pointer got there
    (the cursor-shape test covers that). On a real desktop the actual mouse is
    somewhere else, over the terminal running the tests, and Windows tells
    the window the mouse has left before it can be grabbed, which removes the
    tool cursor exactly as it should in real use.
    """
    canvas._pointer = QPointF(point)
    canvas._sync_cursor()
    canvas.update()


def _hover(widget, point):
    """A mouse move with no button held, delivered straight to the widget.

    Not QTest.mouseMove: on a real desktop that moves the actual pointer, and
    the move only reaches the widget if its window is on top under the pointer,
    which a test window opened behind a terminal is not.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    local = QPointF(point)
    event = QMouseEvent(
        QEvent.Type.MouseMove, local, QPointF(widget.mapToGlobal(point)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def test_the_tool_replaces_the_pointer_only_over_the_screenshot(canvas):
    from PySide6.QtCore import QPointF as P

    canvas.set_tool("pen")
    target = canvas._target()
    _hover(canvas, target.center().toPoint())
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    canvas._pointer = P(target.left() - 0.5, target.top() - 5)
    canvas._sync_cursor()
    assert canvas.cursor().shape() == Qt.CursorShape.ArrowCursor
    canvas.set_tool(None)
    _hover(canvas, target.center().toPoint())
    assert canvas.cursor().shape() == Qt.CursorShape.ArrowCursor


@pytest.mark.parametrize("tool,key,value,expected", [
    ("pen", "pen_width", 9, 9.0),
    ("highlighter", "highlighter_width", 30, 30.0),
    ("eraser", None, None, an.ERASER_RADIUS * 2.0),
    ("crop", None, None, 0.0),
])
def test_the_cursor_shows_the_real_size(canvas, tool, key, value, expected):
    if key:
        canvas.prefs[key] = value
    canvas.set_tool(tool)
    assert canvas.footprint() == expected


def _colour_at(canvas, point) -> str:
    """The colour on screen at a point in the canvas, at any display scaling.

    grab() returns physical pixels: at 300% scaling the image is three times
    the canvas, so a logical point has to be scaled before it is read.
    """
    shot = canvas.grab().toImage()
    ratio = shot.devicePixelRatio()
    return shot.pixelColor(int(point.x() * ratio), int(point.y() * ratio)).name()


def test_the_tool_is_drawn_where_the_pointer_is(canvas):
    canvas.prefs["pen_color"] = "#16c60c"
    canvas.prefs["pen_width"] = 16
    canvas.set_tool("pen")
    centre = canvas._target().center().toPoint()
    _point_at(canvas, centre)
    assert _colour_at(canvas, centre) == "#16c60c"
    # Nothing is drawn while no tool is in hand.
    canvas.set_tool(None)
    assert _colour_at(canvas, centre) == "#ffffff"


# -- 0.7.2: badges, restyling redactions, the right-click menu ------------------------------
@pytest.mark.parametrize("tool,badged", [
    ("pen", False), ("highlighter", False), ("eraser", False), ("crop", True), ("redact", True),
])
def test_only_crop_and_redact_carry_a_badge(tool, badged):
    assert (tool in an.BADGED_TOOLS) is badged


def test_the_pen_cursor_has_no_badge_beside_it(canvas):
    canvas.prefs["pen_width"] = 6
    canvas.set_tool("pen")
    centre = canvas._target().center().toPoint()
    _point_at(canvas, centre)
    assert _colour_at(canvas, centre) == "#e81123"  # the dot is drawn...
    # ...and where the badge used to sit (down and to the right) is untouched snip.
    assert _colour_at(canvas, centre + QPoint(22, 22)) == "#ffffff"


def test_crop_still_carries_its_badge(canvas):
    canvas.set_tool("crop")
    centre = canvas._target().center().toPoint()
    _point_at(canvas, centre)
    assert _colour_at(canvas, centre + QPoint(22, 22)) != "#ffffff"


def test_a_redaction_can_be_switched_and_switched_back_with_undo():
    doc = an.AnnotationDoc(_striped())
    box = an.Redact(doc.new_id(), QRect(20, 40, 100, 20), "black")
    doc.add(box)
    assert _px(doc.render(), 60, 50) == "#000000"
    doc.add(an.Restyle(doc.new_id(), box.id, "blur"))
    assert doc.redact_mode(box) == "blur"
    assert _px(doc.render(), 60, 50) != "#000000"
    doc.undo()
    assert doc.redact_mode(box) == "black" and _px(doc.render(), 60, 50) == "#000000"


def test_the_topmost_redaction_is_the_one_found():
    doc = an.AnnotationDoc(_image())
    under = an.Redact(doc.new_id(), QRect(10, 10, 100, 60), "black")
    over = an.Redact(doc.new_id(), QRect(40, 20, 40, 30), "blur")
    doc.add(under)
    doc.add(over)
    assert doc.redaction_at(QPointF(50, 30)) is over
    assert doc.redaction_at(QPointF(15, 15)) is under
    assert doc.redaction_at(QPointF(150, 90)) is None
    doc.add(an.Erase(doc.new_id(), frozenset({over.id})))
    assert doc.redaction_at(QPointF(50, 30)) is under


def _labels(rows):
    return [row[0] if row else "--" for row in rows]


def test_right_click_on_a_redaction_offers_both_modes(canvas):
    box = an.Redact(canvas.doc.new_id(), QRect(50, 50, 100, 60), "black")
    canvas.doc.add(box)
    canvas._refresh()
    canvas.set_tool("pen")  # works with a tool in hand too
    rows = canvas.context_actions(canvas.to_widget(QPointF(100, 80)))
    assert _labels(rows) == ["Black out this redaction", "Blur this redaction"]
    assert rows[0][2] is True and rows[1][2] is False
    edits = []
    canvas.edited.connect(lambda: edits.append(1))
    rows[1][1]()
    assert canvas.doc.redact_mode(box) == "blur" and edits == [1]
    rows[1][1]()  # already blur: no extra step
    assert len(canvas.doc.ops) == 2


def test_right_click_with_no_tool_offers_save_as_and_copy(canvas):
    asked = []
    canvas.save_as_requested.connect(lambda: asked.append("save"))
    canvas.copy_requested.connect(lambda: asked.append("copy"))
    rows = canvas.context_actions(canvas._target().center())
    assert _labels(rows) == ["Save as...", "Copy"]
    rows[0][1]()
    rows[1][1]()
    assert asked == ["save", "copy"]


def test_on_a_redaction_with_no_tool_both_menus_show(canvas):
    canvas.doc.add(an.Redact(canvas.doc.new_id(), QRect(50, 50, 100, 60), "black"))
    canvas._refresh()
    rows = canvas.context_actions(canvas.to_widget(QPointF(100, 80)))
    assert _labels(rows) == ["Black out this redaction", "Blur this redaction", "--", "Save as...", "Copy"]


def test_with_a_tool_in_hand_a_right_click_elsewhere_offers_nothing(canvas):
    canvas.set_tool("highlighter")
    assert canvas.context_actions(canvas._target().center()) == []


def test_right_click_off_the_snip_offers_nothing(canvas):
    target = canvas._target()
    assert canvas.context_actions(QPointF(target.left() - 0.5, target.top() - 5)) == []
