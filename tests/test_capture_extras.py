"""Delayed snips, the snipping magnifier, covered windows, and the 0.13 mark-up extras."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import annotate as an
import capture
import countdown
import edits
import main
import ocr
import overlay
import winlist


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- delayed snips --------------------------------------------------------------------------------
@pytest.mark.parametrize("args, seconds", [
    (["--snip", "--delay", "5"], 5),
    (["--snip", "--delay=10"], 10),
    (["--snip", "--delay", "999"], countdown.MAX_DELAY),
    (["--snip", "--delay", "soon"], 0),
    (["--snip"], 0),
    (["--snip", "--delay"], 0),
])
def test_delay_from_the_command_line(args, seconds):
    assert countdown.parse_delay(args) == seconds


def test_a_delayed_snip_asks_a_running_copy_with_its_delay():
    assert main.request_for(True, False, False, 5) == b"snip:5"
    assert main.request_for(True, False, False) == b"snip"


class FakePreview:
    def __init__(self, visible=True):
        self.visible, self.events = visible, []

    def flush_edits(self):
        self.events.append("flush")

    def hide_viewer(self):
        self.events.append("hide_viewer")

    def isVisible(self):
        return self.visible

    def isMinimized(self):
        return False

    def hide(self):
        self.visible = False
        self.events.append("hide")


@pytest.fixture
def snipper(monkeypatch):
    import app as app_mod

    state = app_mod.ShadowSnipApp.__new__(app_mod.ShadowSnipApp)
    QObject.__init__(state)
    state.busy = False
    state.preview = FakePreview()
    state.action_cancel_delay = SimpleNamespace(enabled=False, setEnabled=lambda on: setattr(
        state.action_cancel_delay, "enabled", on))
    snips, shows = [], []
    monkeypatch.setattr(state, "request_snip", lambda: snips.append(True), raising=False)
    monkeypatch.setattr(state, "show_window", lambda: shows.append(True), raising=False)
    yield state, snips, shows
    if getattr(state, "_delay_timer", None) is not None:
        state._delay_timer.stop()
        state.countdown.hide()


def test_countdown_hides_the_window_and_snips_at_zero(snipper, monkeypatch):
    state, snips, _shows = snipper
    later = []
    monkeypatch.setattr("app.QTimer.singleShot", lambda ms, fn: later.append((ms, fn)))
    state.request_snip_delayed(3)
    assert state.preview.events[-1] == "hide" and state.counting_down
    assert state.countdown.isVisible() and "3" in state.countdown.text()
    assert state.action_cancel_delay.enabled
    state._count_down()
    state._count_down()
    assert snips == [] and "1" in state.countdown.text()
    state._count_down()
    assert not state.counting_down and not state.countdown.isVisible()
    # The snip waits a moment after the countdown is gone, so it is not in the picture.
    (ms, fn), = later
    assert ms == state.COUNTDOWN_CLEAR_MS
    fn()
    assert snips == [True]


def test_cancel_stops_the_countdown_and_brings_the_window_back(snipper):
    state, snips, shows = snipper
    state.request_snip_delayed(5)
    state.cancel_delayed_snip()
    assert not state.counting_down and not state.countdown.isVisible()
    assert shows == [True] and snips == []


def test_no_delay_is_an_ordinary_snip(snipper):
    state, snips, _shows = snipper
    state.request_snip_delayed(0)
    assert snips == [True] and not state.counting_down


def test_the_countdown_never_takes_focus_or_clicks():
    clock = countdown.Countdown()
    assert clock.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert clock.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_snip_hotkey_during_a_countdown_snips_now(monkeypatch):
    import app as app_mod

    stopped = []
    timer = SimpleNamespace(isActive=lambda: True, stop=lambda: stopped.append(True))
    monkeypatch.setattr(app_mod, "_modal_dialog_open", lambda: False)
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda _ms, fn: None)
    state = SimpleNamespace(
        busy=False, _delay_timer=timer,
        countdown=SimpleNamespace(hide=lambda: stopped.append("hidden")),
        action_cancel_delay=SimpleNamespace(setEnabled=lambda on: None),
        _reshow_after_delay=True,
        autocopy=SimpleNamespace(pause=lambda: None),
        toast=SimpleNamespace(hide=lambda: None),
        preview=SimpleNamespace(isVisible=lambda: False, hide=lambda: None, hide_viewer=lambda: None,
                                flush_edits=lambda: False),
        _blocked_by_dialog=lambda: None, _begin_snip=lambda: None,
    )
    app_mod.ShadowSnipApp.request_snip(state)
    assert stopped == [True, "hidden"] and state.busy
    # The window the countdown hid comes back after this snip.
    assert state._reshow_preview is True


def test_the_preview_offers_delays():
    import preview

    window = preview.PreviewWindow()
    asked = []
    window.delayed_snip_requested.connect(asked.append)
    actions = window.btn_delay.menu().actions()
    assert [a.text() for a in actions] == [f"Snip in {s} seconds" for s in countdown.DELAYS]
    actions[1].trigger()
    assert asked == [countdown.DELAYS[1]]
    window.close()


# -- the magnifier while snipping ---------------------------------------------------------------
def test_loupe_sits_below_right_and_flips_at_edges():
    screen = QRect(0, 0, 1000, 800)
    near = overlay.loupe_place(QPoint(100, 100), screen)
    assert near.left() > 100 and near.top() > 100
    corner = overlay.loupe_place(QPoint(990, 790), screen)
    assert corner.right() < 990 and corner.bottom() < 790


def _middle() -> QPoint:
    from PySide6.QtGui import QGuiApplication

    # The middle of whatever screen there is: at 300% the test screen is tiny.
    return QGuiApplication.primaryScreen().geometry().center()


def _grab():
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

    screen = QGuiApplication.primaryScreen()
    pixmap = QPixmap(screen.geometry().size())
    pixmap.fill(QColor("#336699"))
    p = QPainter(pixmap)
    middle = _middle()
    p.fillRect(QRect(middle.x() - 5, middle.y() - 5, 10, 10), QColor("#ffffff"))
    p.end()
    return capture.ScreenGrab(screen=screen, pixmap=pixmap, scale=1.0)


@pytest.fixture
def live():
    pointer = [_middle()]
    ctrl = overlay.SelectionController([_grab()], button_down=None, cursor_pos=lambda: pointer[0])
    ctrl.start()
    QApplication.processEvents()
    yield ctrl, ctrl._windows[0], pointer
    if not ctrl._finished:
        ctrl.cancel()


def test_the_magnifier_shows_the_real_pixels_under_the_pointer(live):
    ctrl, window, _pointer = live
    box = ctrl.loupe_rect(ctrl.pointer)
    assert not box.isNull()
    picture = window.grab().toImage()
    ratio = picture.devicePixelRatio() or 1.0

    def colour(x, y):
        return QColor(picture.pixel(int(x * ratio), int(y * ratio)))

    middle = (box.x() + 1 + overlay.LOUPE_SIDE // 2 - 3, box.y() + 1 + overlay.LOUPE_SIDE // 2 - 3)
    assert colour(*middle) == QColor("#ffffff")  # the pixel under the pointer, undimmed
    assert colour(box.x() + 4, box.y() + 4) == QColor("#336699")
    screen = window.rect()
    outside = [(x, y) for x, y in ((2, 2), (screen.width() - 3, 2), (2, screen.height() - 3),
                                   (screen.width() - 3, screen.height() - 3))
               if not box.contains(QPoint(x, y)) and not overlay.bar_rect(screen.width()).contains(QPoint(x, y))]
    assert outside and colour(*outside[0]) != QColor("#336699")  # the rest is dimmed


def test_m_hides_the_magnifier_and_window_mode_has_none(live):
    from PySide6.QtTest import QTest

    ctrl, window, _pointer = live
    QTest.keyClick(window, Qt.Key.Key_M)
    assert ctrl.loupe_rect(ctrl.pointer).isNull()
    QTest.keyClick(window, Qt.Key.Key_M)
    assert not ctrl.loupe_rect(ctrl.pointer).isNull()
    ctrl._windows_on_screen = [QRect(0, 0, 50, 50)]
    ctrl.set_mode("window")
    assert ctrl.loupe_rect(ctrl.pointer).isNull()


def test_the_magnifier_setting_reaches_the_overlay(monkeypatch):
    import config

    cfg = config._sanitise({**dict(config.DEFAULTS), "snip_magnifier": 0})
    assert cfg["snip_magnifier"] is False and config.DEFAULTS["snip_magnifier"] is True


# -- covered windows ----------------------------------------------------------------------------
def test_covered_windows_are_marked():
    top = winlist.Window(QRect(100, 100, 300, 200), 1)
    under = winlist.Window(QRect(0, 0, 400, 300), 2)
    apart = winlist.Window(QRect(900, 900, 100, 100), 3)
    windows = [top, under, apart]
    winlist.mark_covered(windows)
    assert [w.covered for w in windows] == [False, True, False]
    assert winlist.window_at(windows, QPoint(150, 150)) is top


def test_a_black_capture_counts_as_failed():
    black = QImage(200, 100, QImage.Format.Format_RGB32)
    black.fill(QColor("#000000"))
    assert winlist.mostly_black(black)
    terminal = QImage(200, 100, QImage.Format.Format_RGB32)
    terminal.fill(QColor("#000000"))
    from PySide6.QtGui import QPainter

    p = QPainter(terminal)
    p.fillRect(QRect(0, 0, 200, 12), QColor("#2b2b2b"))  # a title bar
    p.end()
    assert not winlist.mostly_black(terminal)


def test_capture_window_is_windows_only():
    if winlist.sys.platform != "win32":
        assert winlist.capture_window(1234) is None
    assert winlist.capture_window(0) is None


def _app_for_selection(monkeypatch, picked, direct):
    import app as app_mod

    state = SimpleNamespace(
        controller=SimpleNamespace(shape=None, picked_window=picked), _grabs=["grab"],
        _reshow_preview=False, busy=True, autocopy=SimpleNamespace(resume=lambda: None),
        preview=SimpleNamespace(open_window=lambda: None),
    )
    handled = []
    state._handle_snip = handled.append
    screen = QImage(10, 10, QImage.Format.Format_RGB32)
    monkeypatch.setattr(capture, "compose_selection", lambda grabs, rect: screen)
    monkeypatch.setattr(winlist, "capture_window", lambda handle: direct)
    app_mod.ShadowSnipApp._on_selected(state, QRect(0, 0, 10, 10))
    return handled, screen


def test_a_covered_window_is_taken_from_the_window(monkeypatch):
    direct = QImage(20, 20, QImage.Format.Format_RGB32)
    handled, _screen = _app_for_selection(monkeypatch, winlist.Window(QRect(0, 0, 10, 10), 7, True), direct)
    assert handled == [direct]


def test_a_covered_window_that_will_not_draw_comes_from_the_screen(monkeypatch):
    handled, screen = _app_for_selection(monkeypatch, winlist.Window(QRect(0, 0, 10, 10), 7, True), None)
    assert handled == [screen]


def test_an_uncovered_window_comes_from_the_screen(monkeypatch):
    direct = QImage(20, 20, QImage.Format.Format_RGB32)
    handled, screen = _app_for_selection(monkeypatch, winlist.Window(QRect(0, 0, 10, 10), 7, False), direct)
    assert handled == [screen]


def test_clicking_a_window_remembers_which(monkeypatch):
    window = winlist.Window(QRect(10, 10, 100, 100), 9, True)
    ctrl = overlay.SelectionController([], button_down=None, cursor_pos=lambda: QPoint(20, 20),
                                       mode="window", window_source=lambda: [window])
    got = []
    ctrl.selected.connect(got.append)
    ctrl.click_window()
    assert got == [QRect(10, 10, 100, 100)] and ctrl.picked_window is window


# -- mark-up extras -----------------------------------------------------------------------------
def _image(colour="#808080"):
    img = QImage(400, 200, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


def test_blur_box_blurs_and_can_be_moved():
    from PySide6.QtGui import QPainter

    base = _image("#000000")
    p = QPainter(base)
    p.fillRect(QRect(50, 50, 4, 40), QColor("#ffffff"))
    p.end()
    doc = an.AnnotationDoc(base)
    blur = an.Mark(doc.new_id(), "blur", "#e81123", QPointF(30, 30), QPointF(90, 110))
    doc.add(blur)
    out = doc.render()
    assert QColor(out.pixel(51, 70)) != QColor("#ffffff")  # the stripe is softened
    assert QColor(out.pixel(150, 70)) == QColor("#000000")  # nothing outside it changes
    assert doc.mark_at(QPointF(60, 60), 1).kind == "blur"   # clickable anywhere inside
    doc.add(an.Change(doc.new_id(), blur.id, {"a": QPointF(130, 30), "b": QPointF(190, 110)}))
    assert QColor(doc.render().pixel(51, 70)) == QColor("#ffffff")


def test_blur_is_a_shape_choice():
    assert "blur" in an.SHAPE_KINDS and an.sanitise_prefs({"shape_kind": "blur"})["shape_kind"] == "blur"


@pytest.fixture
def canvas():
    widget = an.AnnotCanvas()
    widget.resize(420, 220)
    widget.show()
    widget.load(_image())
    QApplication.processEvents()
    yield widget
    widget.close()


def _label(canvas, size=16.0):
    mark = an.Mark(canvas.doc.new_id(), "label", "#e81123", QPointF(50, 50), QPointF(50, 50),
                   size=size, text="hi")
    canvas.doc.add(mark)
    canvas._refresh()
    return mark


def test_a_marks_colour_changes_from_its_menu_and_undoes(canvas):
    mark = _label(canvas)
    rows = [r for r in canvas.context_actions(QPointF(canvas.to_widget(QPointF(55, 58)))) if r]
    colours = next(callback for label, callback, _checked in rows if label == "Colour")
    blue = next(cb for name, cb, swatch in colours if name == "Blue")
    blue()
    assert canvas.doc.effective(mark).color == "#0091ff"
    canvas.undo()
    assert canvas.doc.effective(mark).color == "#e81123"


def test_larger_and_smaller_step_the_size(canvas):
    mark = _label(canvas, size=16.0)
    canvas.resize_mark(mark.id, an.SIZE_STEP)
    assert canvas.doc.effective(mark).size == pytest.approx(20.0)
    canvas.resize_mark(mark.id, 1 / an.SIZE_STEP)
    assert canvas.doc.effective(mark).size == pytest.approx(16.0)


def test_strip_options_restyle_the_selected_mark(canvas):
    mark = _label(canvas)
    canvas.set_tool("select")
    canvas._selected = mark.id
    before = dict(canvas.prefs)
    after = {**before, "mark_color": "#16c60c", "text_size": 30}
    canvas.restyle_selected(before, after)
    now = canvas.doc.effective(mark)
    assert now.color == "#16c60c" and now.size == pytest.approx(canvas._image_size(30))


def test_strip_options_leave_marks_alone_without_select(canvas):
    mark = _label(canvas)
    canvas.set_tool("label")
    canvas.restyle_selected(dict(canvas.prefs), {**canvas.prefs, "mark_color": "#16c60c"})
    assert canvas.doc.effective(mark).color == "#e81123"


def test_right_clicking_a_mark_tool_keeps_select_in_hand():
    strip = an.AnnotToolbar()
    strip.select("select")
    strip._on_tool_right_clicked("shape")
    assert strip.tool == "select"
    strip.mark_popups["shape"].hide()
    strip.select("pen")
    strip._on_tool_right_clicked("shape")
    assert strip.tool == "shape"
    strip.mark_popups["shape"].hide()
    strip.close()


def test_style_changes_survive_the_sidecar(tmp_path):
    doc = an.AnnotationDoc(_image())
    mark = an.Mark(doc.new_id(), "arrow", "#e81123", QPointF(10, 10), QPointF(100, 100), width=4)
    doc.add(mark)
    doc.add(an.Change(doc.new_id(), mark.id, {"color": "#0091ff", "width": 9.5}))
    snip = tmp_path / "s.png"
    data = an._png_of(doc.render())
    snip.write_bytes(data)
    assert edits.save(snip, doc, data)
    back = edits.load(snip)
    now = back.effective(back.ops[0])
    assert now.color == "#0091ff" and now.width == pytest.approx(9.5)


# -- Quick redact: the lab's own targets ------------------------------------------------------------
def W(text, x, line=0):
    return ocr.Word(text, x, 10 + line * 20, 8 * len(text), 14, line)


def _line(text, line=0):
    words, x = [], 4
    for part in text.split(" "):
        words.append(W(part, x, line))
        x += 8 * len(part) + 8
    return words


def test_lab_targets_are_found_as_whole_tokens():
    words = _line("ping 10.10.10.3 and 10.10.10.30 on dc01.corp.local")
    found = ocr.find_sensitive(words, kinds={"target"}, targets=["10.10.10.3", "corp.local", "dc01.corp.local"])
    assert sorted(f.text for f in found) == ["10.10.10.3", "dc01.corp.local"]


def test_lab_targets_are_case_blind_and_need_a_lab():
    words = _line("connected to DC01.CORP.LOCAL")
    assert [f.kind for f in ocr.find_sensitive(words, targets=["dc01.corp.local"])] == ["target"]
    assert ocr.find_sensitive(words, kinds={"target"}) == []  # no lab running


def test_an_email_still_wins_over_its_domain():
    words = _line("mail admin@corp.local now")
    found = ocr.find_sensitive(words, targets=["corp.local"])
    assert [(f.kind, f.text) for f in found] == [("email", "admin@corp.local")]


def test_targets_come_from_findings_and_host_sections(monkeypatch):
    import lab

    monkeypatch.setattr(lab, "is_active", lambda cfg: True)
    monkeypatch.setattr(lab, "findings", lambda cfg: [{"host": "dc01.corp.local, 10.10.10.5"}])
    monkeypatch.setattr(lab, "sections", lambda cfg: ["Recon", "10.10.10.3/SMB", "Privilege escalation"])
    got = set(lab.targets({}))
    assert got == {"dc01.corp.local", "corp.local", "10.10.10.5", "10.10.10.3"}
    monkeypatch.setattr(lab, "is_active", lambda cfg: False)
    assert lab.targets({}) == []


def test_the_app_points_quick_redact_at_the_lab():
    ocr.target_source = lambda: ["10.10.10.3"]
    assert ocr.lab_targets() == ["10.10.10.3"]

    def broken():
        raise OSError("lab gone")

    ocr.target_source = broken
    assert ocr.lab_targets() == []
