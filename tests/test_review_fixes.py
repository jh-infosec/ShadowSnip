"""Fixes from the external review of v0.5.0.

1. A lab name could write outside the labs folder.
2. A triple-click could copy the word and then the line.
3. Switching image format could lose the latest snip if the new write failed.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

import autocopy
import lab
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- 1. lab names stay inside the labs root ----------------------------------
@pytest.mark.parametrize(
    "name",
    [
        "..",
        ".",
        "../escape",
        "..\\..\\Documents\\other",
        "sub/dir",
        "sub\\dir",
        "C:evil",
        "C:\\Windows\\Temp",
        "/etc",
        "CON",
        "nul.txt",
        "com1",
        "LPT9",
        "trailing.",
        "bad*name",
        'quote"name',
        "tab\tname",
        "x" * (lab.MAX_NAME + 1),
    ],
)
def test_names_that_could_leave_the_root_are_refused(cfg, tmp_path, name):
    before = set(tmp_path.rglob("*"))
    with pytest.raises(lab.LabError):
        lab.start(cfg, name)
    created = set(tmp_path.rglob("*")) - before
    assert not any(p.name in (lab.STATE_NAME, lab.INDEX_NAME) for p in created)


@pytest.mark.parametrize(
    "name",
    ["htb-lame", "client internal 2026", "10.10.10.3", "box_01", "con-test", "a.b", "émile"],
)
def test_ordinary_names_still_work(cfg, name):
    path = lab.start(cfg, name)
    assert path.parent == lab.root(cfg)
    assert path.name == name


def test_a_bad_stored_name_means_no_lab_rather_than_writing_elsewhere(cfg, tmp_path):
    cfg["active_lab"] = "..\\..\\outside"
    assert lab.active_name(cfg) == ""
    assert lab.active_folder(cfg) is None
    assert not lab.is_active(cfg)
    assert lab.save(b"x", "png", cfg) is None


def test_folder_refuses_a_path_that_resolves_outside_the_root(cfg, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    root = lab.root(cfg)
    root.mkdir(parents=True)
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    with pytest.raises(lab.LabError):
        lab.folder(cfg, "linked")


def test_the_reason_is_given(cfg):
    with pytest.raises(lab.LabError, match="cannot contain"):
        lab.start(cfg, "a/b")
    with pytest.raises(lab.LabError, match="reserved"):
        lab.start(cfg, "AUX")


# -- 2. one copy per click run -------------------------------------------------
class _Recorder:
    def __init__(self, copy):
        self.kinds = []
        copy._capture = lambda kind="selection": self.kinds.append(kind)


def _clicks(copy, times):
    for when in times:
        copy._on_press(100, 100, when)
        copy._on_release((100, 100), (100, 100))


def _copy():
    copy = autocopy.AutoCopy({"auto_copy_double_click": True, "auto_copy_min_drag": 8})
    copy._run = autocopy._ClickRun(500, (2, 2))
    return copy


def test_a_double_click_waits_out_the_double_click_interval():
    copy = _copy()
    rec = _Recorder(copy)
    _clicks(copy, [1000, 1100])
    assert copy._click_timer.isActive()
    assert copy._click_timer.interval() == 500
    assert copy._click_kind == "word"
    copy._click_timer.timeout.emit()
    assert rec.kinds == ["word"]


def test_a_triple_click_copies_the_line_only():
    copy = _copy()
    rec = _Recorder(copy)
    _clicks(copy, [1000, 1100, 1200])
    # The word copy from the second click was replaced, not added to.
    assert copy._click_kind == "line"
    assert copy._click_timer.interval() == autocopy.DOUBLE_CLICK_SETTLE_MS
    copy._click_timer.timeout.emit()
    assert rec.kinds == ["line"]


def test_the_third_press_holds_the_pending_word_copy():
    copy = _copy()
    _Recorder(copy)
    _clicks(copy, [1000, 1100])
    copy._on_press(100, 100, 1200)
    assert not copy._click_timer.isActive()


def test_a_drag_cancels_a_pending_click_copy():
    copy = _copy()
    rec = _Recorder(copy)
    autocopy_single = []
    _clicks(copy, [1000, 1100])
    copy._on_press(100, 100, 5000)
    original = autocopy.QTimer.singleShot
    try:
        autocopy.QTimer.singleShot = lambda _ms, fn: autocopy_single.append(fn)
        copy._on_release((100, 100), (300, 100))
    finally:
        autocopy.QTimer.singleShot = original
    assert not copy._click_timer.isActive()
    assert len(autocopy_single) == 1 and rec.kinds == []


def test_pausing_cancels_a_pending_click_copy():
    copy = _copy()
    _Recorder(copy)
    _clicks(copy, [1000, 1100])
    copy.pause()
    assert not copy._click_timer.isActive()


# -- 3. the latest snip survives a failed write --------------------------------
def test_switching_format_keeps_the_old_file_if_the_new_write_fails(cfg, monkeypatch):
    old = storage.save_latest(b"old png", "png", cfg)

    def fail(path, data):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "write_atomic", fail)
    with pytest.raises(OSError):
        storage.save_latest(b"new webp", "webp", cfg)

    assert old.read_bytes() == b"old png"


def test_switching_format_still_removes_the_old_file_on_success(cfg):
    old = storage.save_latest(b"old png", "png", cfg)
    new = storage.save_latest(b"new webp", "webp", cfg)
    assert new.read_bytes() == b"new webp"
    assert not old.exists()
