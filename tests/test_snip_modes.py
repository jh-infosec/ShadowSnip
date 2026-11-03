"""Window and freeform snips, the mode bar, the colour picker, Print Screen and Alt+N (0.12.0)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QPolygon, QShortcut
from PySide6.QtWidgets import QApplication

import annotate as an
import capture
import config
import hotkey
import hotkey_linux
import overlay
import winlist


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- the window list ------------------------------------------------------------------------------
def test_to_logical_uses_the_monitor_the_window_is_on():
    monitors = [
        (QRect(0, 0, 1920, 1080), QRect(0, 0, 1920, 1080)),           # 100%
        (QRect(1920, 0, 3840, 2160), QRect(1920, 0, 2560, 1440)),     # 150%
    ]
    assert winlist.to_logical(QRect(100, 100, 800, 600), monitors) == QRect(100, 100, 800, 600)
    assert winlist.to_logical(QRect(1920 + 300, 150, 1500, 900), monitors) == QRect(2120, 100, 1000, 600)


def test_to_logical_off_every_monitor_uses_the_nearest():
    monitors = [(QRect(0, 0, 2000, 1000), QRect(0, 0, 1000, 500))]
    assert winlist.to_logical(QRect(2200, 0, 200, 100), monitors) == QRect(1100, 0, 100, 50)
    assert winlist.to_logical(QRect(5, 5, 10, 10), []) == QRect(5, 5, 10, 10)


def test_window_at_takes_the_topmost():
    top, under = QRect(100, 100, 300, 200), QRect(0, 0, 800, 600)
    assert winlist.window_at([top, under], QPoint(150, 150)) == top
    assert winlist.window_at([top, under], QPoint(700, 500)) == under
    assert winlist.window_at([top, under], QPoint(900, 900)) is None


def test_x11_output_is_parsed():
    ids = winlist.parse_client_list("_NET_CLIENT_LIST_STACKING(WINDOW): window id # 0x1a00003, 0x2000001")
    assert ids == ["0x1a00003", "0x2000001"]
    assert winlist.parse_client_list("_NET_CLIENT_LIST_STACKING:  not found.") == []
    info = ("  Absolute upper-left X:  100\n  Absolute upper-left Y:  145\n"
            "  Width: 300\n  Height: 200\n  Map State: IsViewable\n")
    assert winlist.parse_xwininfo(info) == QRect(100, 145, 300, 200)
    assert winlist.parse_xwininfo(info.replace("IsViewable", "IsUnMapped")) is None
    props = ("_NET_FRAME_EXTENTS(CARDINAL) = 1, 1, 24, 1\n"
             "_NET_WM_STATE(ATOM) = _NET_WM_STATE_HIDDEN\n_NET_WM_PID(CARDINAL) = 4242\n")
    assert winlist.parse_xprop(props) == ((1, 1, 24, 1), True, 4242)
    assert winlist.parse_xprop("") == ((0, 0, 0, 0), False, None)


def test_tiny_windows_and_failures_are_left_out(monkeypatch):
    monkeypatch.setattr(winlist.sys, "platform", "linux")
    monkeypatch.setattr(winlist, "_windows_x11", lambda: [QRect(0, 0, 400, 300), QRect(0, 0, 5, 5)])
    assert winlist.visible_windows() == [QRect(0, 0, 400, 300)]

    def broken():
        raise OSError("no X")

    monkeypatch.setattr(winlist, "_windows_x11", broken)
    assert winlist.visible_windows() == []


# -- the controller's modes -----------------------------------------------------------------------
class Mouse:
    def __init__(self):
        self.pos = QPoint(0, 0)

    def cursor(self):
        return self.pos


def _controller(mode="rect", windows=()):
    mouse = Mouse()
    ctrl = overlay.SelectionController([], button_down=None, cursor_pos=mouse.cursor,
                                       mode=mode, window_source=lambda: list(windows))
    got, modes = [], []
    ctrl.selected.connect(got.append)
    ctrl.cancelled.connect(lambda: got.append("cancelled"))
    ctrl.mode_changed.connect(modes.append)
    return ctrl, mouse, got, modes


def test_window_mode_takes_the_window_under_the_pointer():
    ctrl, mouse, got, _ = _controller("window", [QRect(100, 100, 400, 300), QRect(0, 0, 1000, 800)])
    mouse.pos = QPoint(200, 200)
    ctrl.hover(mouse.pos)
    assert ctrl.hover_window == QRect(100, 100, 400, 300)
    ctrl.click_window()
    assert got == [QRect(100, 100, 400, 300)]


def test_window_mode_click_on_nothing_waits():
    ctrl, mouse, got, _ = _controller("window", [QRect(100, 100, 400, 300)])
    mouse.pos = QPoint(900, 900)
    ctrl.click_window()
    assert got == [] and not ctrl._finished


def test_window_mode_without_windows_falls_back_and_says_so():
    ctrl, _mouse, _got, modes = _controller("rect", [])
    ctrl.set_mode("window")
    assert ctrl.mode == "rect" and "No windows" in ctrl.notice and modes == []


def test_the_window_list_is_read_once_and_only_when_needed():
    calls = []

    def source():
        calls.append(1)
        return [QRect(0, 0, 100, 100)]

    ctrl = overlay.SelectionController([], button_down=None, cursor_pos=lambda: QPoint(5, 5),
                                       window_source=source)
    assert calls == []
    ctrl.set_mode("window")
    ctrl.hover(QPoint(10, 10))
    ctrl.hover(QPoint(20, 20))
    assert calls == [1]


def test_mode_changes_are_announced_to_be_remembered():
    ctrl, _mouse, _got, modes = _controller("rect", [QRect(0, 0, 100, 100)])
    ctrl.set_mode("freeform")
    ctrl.set_mode("freeform")
    ctrl.set_mode("window")
    assert modes == ["freeform", "window"]


def test_an_unknown_mode_is_rectangle():
    ctrl, *_ = _controller("hexagon")
    assert ctrl.mode == "rect"


def test_freeform_snips_the_shapes_bounds_and_keeps_the_shape():
    ctrl, _mouse, got, _ = _controller("freeform")
    ctrl.begin(QPoint(100, 100))
    for point in ((200, 90), (260, 180), (150, 240), (90, 170)):
        ctrl.drag_to(QPoint(*point))
    shape = ctrl.shape
    ctrl.release()
    assert got == [QRect(90, 90, 171, 151)]
    assert shape is not None and shape.size() == 5


def test_freeform_ignores_tiny_moves():
    ctrl, *_ = _controller("freeform")
    ctrl.begin(QPoint(100, 100))
    ctrl.drag_to(QPoint(101, 100))
    assert len(ctrl.path) == 1


def test_a_freeform_scribble_too_small_is_cancelled():
    ctrl, _mouse, got, _ = _controller("freeform")
    ctrl.begin(QPoint(100, 100))
    ctrl.drag_to(QPoint(110, 100))
    ctrl.release()
    assert got == ["cancelled"]


def test_the_mode_cannot_change_mid_drag():
    ctrl, *_ = _controller("rect")
    ctrl.begin(QPoint(10, 10))
    ctrl.set_mode("freeform")
    assert ctrl.mode == "rect"


# -- the bar and keys, on a real overlay window -----------------------------------------------------
def _grab(w=1200, h=700):
    from PySide6.QtGui import QGuiApplication, QPixmap

    screen = QGuiApplication.primaryScreen()
    pixmap = QPixmap(screen.geometry().size())
    pixmap.fill(QColor("#336699"))
    return capture.ScreenGrab(screen=screen, pixmap=pixmap, scale=1.0)


@pytest.fixture
def live():
    mouse = Mouse()
    ctrl = overlay.SelectionController([_grab()], button_down=None, cursor_pos=mouse.cursor,
                                       window_source=lambda: [QRect(50, 300, 300, 200)])
    got = []
    ctrl.selected.connect(got.append)
    ctrl.cancelled.connect(lambda: got.append("cancelled"))
    ctrl.start()
    QApplication.processEvents()
    yield ctrl, ctrl._windows[0], got, mouse
    if not ctrl._finished:
        ctrl.cancel()


def _click(window, pos: QPoint):
    from PySide6.QtTest import QTest

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_the_bar_switches_modes(live):
    ctrl, window, _got, _mouse = live
    items = dict(overlay.bar_layout(window.width()))
    _click(window, items["freeform"].center())
    assert ctrl.mode == "freeform"
    _click(window, items["window"].center())
    assert ctrl.mode == "window"


def test_the_bar_takes_the_full_screen_and_closes(live):
    ctrl, window, got, _mouse = live
    screen = window.grab_info.screen.geometry()
    items = dict(overlay.bar_layout(window.width()))
    _click(window, items["screen"].center())
    assert got == [screen]


def test_clicking_the_bar_does_not_end_the_snip(live):
    ctrl, window, got, _mouse = live
    _click(window, dict(overlay.bar_layout(window.width()))["freeform"].center())
    assert got == [] and not ctrl._finished


def test_the_bars_esc_cancels(live):
    ctrl, window, got, _mouse = live
    _click(window, dict(overlay.bar_layout(window.width()))["close"].center())
    assert got == ["cancelled"]


def test_keys_pick_modes(live):
    from PySide6.QtTest import QTest

    ctrl, window, _got, _mouse = live
    QTest.keyClick(window, Qt.Key.Key_L)
    assert ctrl.mode == "freeform"
    QTest.keyClick(window, Qt.Key.Key_W)
    assert ctrl.mode == "window"
    QTest.keyClick(window, Qt.Key.Key_R)
    assert ctrl.mode == "rect"


def test_bar_buttons_do_not_overlap_and_fit_the_screen():
    items = overlay.bar_layout(1280)
    for (_a, first), (_b, second) in zip(items, items[1:]):
        assert first.right() < second.left()
    frame = overlay.bar_rect(1280)
    assert frame.left() > 0 and frame.right() < 1280


# -- the freeform mask ----------------------------------------------------------------------------
def test_mask_outside_whitens_only_outside_the_shape():
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#000000"))
    rect = QRect(100, 100, 100, 100)  # logical, drawn at 2x
    shape = QPolygon([QPoint(150, 100), QPoint(200, 150), QPoint(150, 200), QPoint(100, 150)])
    out = capture.mask_outside(image, shape, rect)
    assert QColor(out.pixel(2, 2)) == QColor("#ffffff")
    assert QColor(out.pixel(100, 100)) == QColor("#000000")
    assert capture.mask_outside(image, None, rect) is image


# -- the colour picker ----------------------------------------------------------------------------
@pytest.fixture
def canvas():
    img = QImage(400, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("#101010"))
    from PySide6.QtGui import QPainter

    p = QPainter(img)
    p.fillRect(QRect(100, 50, 50, 50), QColor("#2f8cff"))
    p.end()
    widget = an.AnnotCanvas()
    widget.resize(420, 220)
    widget.show()
    widget.load(img)
    QApplication.processEvents()
    yield widget
    widget.close()


def test_picker_reads_and_copies_a_colour(canvas):
    notices = []
    canvas.notice.connect(notices.append)
    assert canvas.colour_at(QPointF(120, 70)) == QColor("#2f8cff")
    assert canvas.copy_colour(QPointF(120, 70)) == "#2f8cff"
    assert QApplication.clipboard().text() == "#2f8cff"
    assert "rgb(47, 140, 255)" in notices[-1]
    assert canvas.copy_colour(QPointF(120, 70), as_rgb=True) == "rgb(47, 140, 255)"


def test_picker_click_copies_and_shift_click_copies_rgb(canvas):
    from PySide6.QtTest import QTest

    canvas.set_tool("picker")
    spot = canvas.to_widget(QPointF(120, 70)).toPoint()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
    assert QApplication.clipboard().text() == "#2f8cff"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, spot)
    assert QApplication.clipboard().text() == "rgb(47, 140, 255)"
    assert canvas.doc.ops == []  # picking is not a mark


def test_picker_reads_the_snip_as_marked_and_cropped(canvas):
    canvas.doc.add(an.Crop(canvas.doc.new_id(), QRect(100, 50, 100, 100)))
    canvas.doc.add(an.Redact(canvas.doc.new_id(), QRect(100, 50, 20, 20), "black"))
    canvas._refresh()
    assert canvas.colour_at(QPointF(110, 60)) == QColor("#000000")
    assert canvas.colour_at(QPointF(130, 80)) == QColor("#2f8cff")
    assert canvas.colour_at(QPointF(10, 10)) is None  # cropped away


def test_picker_is_on_the_strip():
    strip = an.AnnotToolbar()
    assert "picker" in strip.buttons
    strip.close()


# -- Print Screen ---------------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [(1, True), (0, False)])
def test_windows_print_screen_setting_is_read(value, expected):
    assert hotkey.windows_owns_print_screen(read=lambda: value) is expected


def test_print_screen_default_depends_on_the_windows_build(monkeypatch):
    class Version:
        build = 22631

    monkeypatch.setattr(hotkey.sys, "getwindowsversion", lambda: Version(), raising=False)
    assert hotkey.windows_owns_print_screen(read=lambda: None) is True
    Version.build = 19045
    assert hotkey.windows_owns_print_screen(read=lambda: None) is False


def test_linux_knows_the_print_screen_action():
    assert hotkey_linux.ACTION_FLAGS["snip_prtsc"] == "--snip"


class FakeHotkeys:
    def __init__(self, fail=None):
        self.specs, self.fail = {}, fail

    def registered(self, name):
        return name in self.specs

    def register(self, _app, spec, name):
        if self.fail:
            raise hotkey.HotkeyError(self.fail)
        self.specs[name] = spec

    def unregister(self, name=None):
        self.specs.pop(name, None)


class FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, _title, text, *_rest):
        self.messages.append(text)


@pytest.fixture
def snipper(monkeypatch):
    import app as app_mod

    state = app_mod.ShadowSnipApp.__new__(app_mod.ShadowSnipApp)
    from PySide6.QtCore import QObject

    QObject.__init__(state)
    state.cfg = dict(config.DEFAULTS)
    state.cfg["prtsc_snip"] = True
    state.hotkeys = FakeHotkeys()
    state.tray = FakeTray()
    state.qapp = QApplication.instance()
    yield state, monkeypatch
    if getattr(state, "_prtsc_timer", None) is not None:
        state._prtsc_timer.stop()


def test_print_screen_registers_when_free(snipper):
    state, monkeypatch = snipper
    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: False)
    state._sync_print_screen()
    assert state.hotkeys.specs == {"snip_prtsc": "prtsc"} and state.prtsc_problem == ""


def test_print_screen_held_by_windows_waits_and_takes_over_when_freed(snipper):
    state, monkeypatch = snipper
    owned = [True]
    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: owned[0])
    state._sync_print_screen(announce=True)
    assert state.hotkeys.specs == {} and "Accessibility > Keyboard" in state.tray.messages[-1]
    assert state._prtsc_timer.isActive()
    owned[0] = False
    state._sync_print_screen()  # what the timer does
    assert state.hotkeys.specs == {"snip_prtsc": "prtsc"}
    assert not state._prtsc_timer.isActive() and "now snips" in state.tray.messages[-1]


def test_print_screen_off_unregisters(snipper):
    state, monkeypatch = snipper
    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: False)
    state._sync_print_screen()
    state.cfg["prtsc_snip"] = False
    state._sync_print_screen()
    assert state.hotkeys.specs == {}


def test_print_screen_already_the_snip_hotkey_is_not_doubled(snipper):
    state, monkeypatch = snipper
    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: False)
    state.cfg["hotkey"] = "prtsc"
    state._sync_print_screen()
    assert state.hotkeys.specs == {}


def test_print_screen_taken_by_another_program_says_so(snipper):
    state, monkeypatch = snipper
    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: False)
    state.hotkeys = FakeHotkeys(fail="Print Screen is already taken by another program")
    state._sync_print_screen(announce=True)
    assert "already taken" in state.prtsc_problem and state.tray.messages


def test_settings_show_what_blocks_print_screen(monkeypatch):
    import settings_dialog

    monkeypatch.setattr(hotkey, "windows_owns_print_screen", lambda read=None: True)
    cfg = dict(config.DEFAULTS)
    dialog = settings_dialog.SettingsDialog(cfg)
    dialog.show()
    assert dialog.btn_prtsc_windows.isHidden()
    dialog.prtsc_check.setChecked(True)
    assert not dialog.btn_prtsc_windows.isHidden() and "Windows is using" in dialog.prtsc_note.text()
    assert dialog.values()["prtsc_snip"] is True
    dialog.close()


def test_config_keeps_the_new_settings_sane():
    cfg = config._sanitise({**dict(config.DEFAULTS), "snip_mode": "lasso", "prtsc_snip": "yes"})
    assert cfg["snip_mode"] == "rect" and cfg["prtsc_snip"] is True
    assert config._sanitise({**dict(config.DEFAULTS), "snip_mode": "window"})["snip_mode"] == "window"


# -- Alt+N --------------------------------------------------------------------------------------------
def _shortcut(widget, keys: str) -> QShortcut:
    wanted = QKeySequence(keys)
    for shortcut in widget.findChildren(QShortcut):
        if shortcut.key() == wanted:
            return shortcut
    raise AssertionError(f"no {keys} shortcut")


def test_alt_n_asks_for_a_new_snip_from_the_preview_and_the_full_size_view():
    import preview

    window = preview.PreviewWindow()
    asked = []
    window.new_snip_requested.connect(lambda: asked.append("preview"))
    _shortcut(window, "Alt+N").activated.emit()
    import labsnips

    viewer = labsnips.SnipViewer()
    window.snips_panel.viewer = viewer
    viewer.new_snip_requested.connect(window.snips_panel.new_snip_requested.emit)
    _shortcut(viewer, "Alt+N").activated.emit()
    assert asked == ["preview", "preview"]
    viewer.close()
    window.close()
