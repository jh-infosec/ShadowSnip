"""The snip overlay: windows made once and reused, and drags repaint only what moved."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication

import capture
import overlay


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _grabs():
    screen = QGuiApplication.primaryScreen()
    geom = screen.geometry()
    pixmap = QPixmap(geom.width(), geom.height())
    pixmap.fill()
    return [capture.ScreenGrab(screen=screen, pixmap=pixmap, scale=1.0)]


def test_prewarm_makes_a_window_per_screen_without_showing_it():
    ready = overlay.prewarm()
    assert ready >= len(QGuiApplication.screens())
    window = overlay._window_for(QGuiApplication.primaryScreen())
    assert not window.isVisible()


def test_every_snip_reuses_the_same_window():
    first = overlay.SelectionController(_grabs(), button_down=None)
    first.start()
    window = first._windows[0]
    assert window.isVisible()
    first.cancel()
    assert not window.isVisible()
    assert window.grab_info is None  # the frozen frame is let go between snips

    second = overlay.SelectionController(_grabs(), button_down=None)
    second.start()
    assert second._windows[0] is window
    assert window.controller is second
    second.cancel()


def test_a_drag_repaints_only_the_strip_that_changed(monkeypatch):
    ctrl = overlay.SelectionController(_grabs(), button_down=None)
    ctrl.start()
    window = ctrl._windows[0]
    asked = []
    monkeypatch.setattr(window, "update", lambda *args: asked.append(args))
    ctrl.begin(QPoint(100, 100))
    asked.clear()
    ctrl.drag_to(QPoint(160, 140))
    assert asked, "the drag should repaint something"
    full = window.rect()
    for args in asked:
        assert len(args) == 1, "a drag repaint names the region it needs"
        region = args[0]
        assert region.width() * region.height() < full.width() * full.height()
        assert region.contains(QRect(100, 100, 61, 41))
    # The same position again repaints nothing.
    asked.clear()
    ctrl.drag_to(QPoint(160, 140))
    assert asked == []
    ctrl.cancel()


def test_a_region_off_this_screen_is_not_repainted(monkeypatch):
    ctrl = overlay.SelectionController(_grabs(), button_down=None)
    ctrl.start()
    window = ctrl._windows[0]
    asked = []
    monkeypatch.setattr(window, "update", lambda *args: asked.append(args))
    geom = window.grab_info.screen.geometry()
    window.update_global(QRect(geom.right() + 50, geom.bottom() + 50, 20, 20))
    assert asked == []
    window.update_global(QRect(geom.x() + 10, geom.y() + 10, 20, 20))
    assert asked == [(QRect(10, 10, 20, 20),)]
    ctrl.cancel()


def test_the_selection_still_comes_out_right():
    ctrl = overlay.SelectionController(_grabs(), button_down=None)
    got = []
    ctrl.selected.connect(got.append)
    ctrl.start()
    ctrl.begin(QPoint(10, 20))
    ctrl.drag_to(QPoint(110, 70))
    ctrl.release()
    assert got == [QRect(QPoint(10, 20), QPoint(110, 70))]
    assert not ctrl._windows
