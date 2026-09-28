"""A drag that crosses monitors must not end on a lost mouse capture."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

import overlay


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class Mouse:
    def __init__(self):
        self.down = True
        self.pos = QPoint(0, 0)

    def button(self):
        return self.down

    def cursor(self):
        return self.pos


def _controller(mouse, probe=True):
    ctrl = overlay.SelectionController(
        [],
        button_down=mouse.button if probe else None,
        cursor_pos=mouse.cursor,
    )
    got = []
    ctrl.selected.connect(got.append)
    ctrl.cancelled.connect(lambda: got.append("cancelled"))
    return ctrl, got


def test_a_release_with_the_button_still_held_is_ignored():
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(100, 100))
    mouse.pos = QPoint(1900, 500)  # onto the second screen
    ctrl.poll()

    ctrl.release()  # Windows took the capture away; the button is still down

    assert got == []
    assert ctrl.release_lost


def test_after_a_lost_release_polling_follows_and_finishes_the_drag():
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(100, 100))
    ctrl.release()

    mouse.pos = QPoint(2400, 700)
    ctrl.poll()
    assert ctrl.selection == QRect(QPoint(100, 100), QPoint(2400, 700))

    mouse.down = False
    for _ in range(overlay.RELEASE_CONFIRM_POLLS):
        ctrl.poll()

    assert got == [QRect(QPoint(100, 100), QPoint(2400, 700))]


def test_a_single_odd_up_reading_does_not_finish():
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(0, 0))
    ctrl.release()
    mouse.pos = QPoint(50, 50)

    mouse.down = False
    ctrl.poll()
    mouse.down = True
    for _ in range(overlay.RELEASE_CONFIRM_POLLS * 2):
        ctrl.poll()

    assert got == []


def test_a_real_release_finishes_at_once():
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(10, 10))
    mouse.pos = QPoint(300, 200)
    ctrl.poll()

    mouse.down = False
    ctrl.release()

    assert got == [QRect(QPoint(10, 10), QPoint(300, 200))]


def test_polling_never_finishes_a_drag_whose_release_was_not_lost():
    """Only a lost release hands the finish to polling; normally the event decides."""
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(10, 10))
    mouse.pos = QPoint(300, 200)
    mouse.down = False
    for _ in range(20):
        ctrl.poll()

    assert got == []


def test_without_a_button_probe_the_release_is_trusted():
    mouse = Mouse()
    ctrl, got = _controller(mouse, probe=False)
    ctrl.begin(QPoint(10, 10))
    ctrl.drag_to(QPoint(200, 200))

    ctrl.release()

    assert got == [QRect(QPoint(10, 10), QPoint(200, 200))]


def test_a_tiny_selection_still_cancels():
    mouse = Mouse()
    ctrl, got = _controller(mouse)
    ctrl.begin(QPoint(10, 10))
    mouse.down = False
    ctrl.release()

    assert got == ["cancelled"]


def test_the_probe_is_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(overlay.sys, "platform", "linux")
    assert overlay.left_button_down() is None
