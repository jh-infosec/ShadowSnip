"""Trimming clips (0.14.2): the trim bar, re-encoding, undo, and keeping lab.md in step."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import clips
import cliptrim
import config
import lab
import player
import recorder
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cfg(tmp_path):
    out = dict(config.DEFAULTS)
    out.update(save_dir=str(tmp_path / "snips"), keep_history=True, history_limit=20,
               lab_root=str(tmp_path / "labs"), active_lab="")
    return out


def _wait(predicate, ms=15000) -> bool:
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(20)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return bool(predicate())


def _grey_clip(folder: Path, seconds=3.0) -> Path:
    """A real clip whose grey level is 60 x the time it was grabbed, with its poster beside it."""
    from PySide6.QtGui import QGuiApplication

    t0 = []

    def grab(_screen, rect):
        if not t0:
            t0.append(time.monotonic())
        level = int((time.monotonic() - t0[0]) * 60) % 256
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        img.fill(QColor(level, level, level))
        return img

    geom = QGuiApplication.primaryScreen().geometry()
    rec = recorder.Recorder(QRect(geom.x(), geom.y(), 160, 90), folder / "clip.mp4", fps=15, grab=grab)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append(None))
    try:
        rec.start()
    except recorder.RecorderError as exc:
        pytest.skip(f"no video encoder here: {exc}")
    QTimer.singleShot(int(seconds * 1000), rec.stop)
    _wait(lambda: bool(done))
    if not done or done[0] is None:
        pytest.skip("this machine's encoder recorded nothing")
    video = Path(done[0])
    video.with_suffix(".png").write_bytes(clips.make_poster(rec.first_frame, rec.elapsed()))
    return video


def _grey(image: QImage) -> int:
    return image.pixelColor(5, 5).green()


# -- names -----------------------------------------------------------------------------------------
def test_the_original_is_kept_under_a_name_of_its_own(tmp_path):
    video = tmp_path / "007_x.mp4"
    assert cliptrim.untrimmed_of(video) == tmp_path / "007_x.untrimmed.mp4"
    assert cliptrim.is_untrimmed_copy(tmp_path / "007_x.untrimmed.mp4")
    assert not cliptrim.is_untrimmed_copy(video)
    assert not cliptrim.is_trimmed(video)


def test_the_original_moves_with_the_clip(tmp_path):
    poster = tmp_path / "a.png"
    poster.write_bytes(b"png")
    poster.with_suffix(".mp4").write_bytes(b"trimmed")
    cliptrim.untrimmed_of(poster.with_suffix(".mp4")).write_bytes(b"original")
    target = tmp_path / "removed" / "a.png"
    target.parent.mkdir()
    poster.replace(target)
    clips.move_with(poster, target)
    assert (tmp_path / "removed" / "a.mp4").read_bytes() == b"trimmed"
    assert (tmp_path / "removed" / "a.untrimmed.mp4").read_bytes() == b"original"
    assert not list(tmp_path.glob("*.mp4"))


def test_times_to_the_tenth():
    assert player.format_ms(0) == "0:00.0"
    assert player.format_ms(3450) == "0:03.4"
    assert player.format_ms(61_900) == "1:01.9"


# -- the trim bar ----------------------------------------------------------------------------------
@pytest.fixture
def bar():
    widget = player.TrimBar()
    widget.resize(416, 24)
    widget.set_length(10_000)
    widget.show()
    yield widget
    widget.close()


def test_the_bar_maps_time_to_place_and_back(bar):
    for ms in (0, 2500, 10_000):
        assert abs(bar.ms_at(bar.x_of(ms)) - ms) <= 30


def test_the_ends_never_cross_or_meet(bar):
    changes = []
    bar.range_changed.connect(lambda a, b: changes.append((a, b)))
    bar.set_range(3000, 7000)
    assert (bar.start, bar.end) == (3000, 7000)
    bar.set_range(6950, 7000)        # the start pushed against the end
    assert bar.end - bar.start >= cliptrim.MIN_KEEP_MS
    bar.set_range(-50, 99_999)
    assert (bar.start, bar.end) == (0, 10_000)
    assert changes[-1] == (0, 10_000)


def test_dragging_a_handle_moves_that_end(bar):
    seeks = []
    bar.seek_requested.connect(seeks.append)
    start_x = int(bar.x_of(0))
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(start_x, 12))
    QTest.mouseMove(bar, QPoint(int(bar.x_of(4000)), 12))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(int(bar.x_of(4000)), 12))
    assert abs(bar.start - 4000) <= 50 and bar.end == 10_000
    assert seeks and abs(seeks[-1] - bar.start) <= 1


def test_clicking_elsewhere_moves_the_play_position(bar):
    seeks = []
    bar.seek_requested.connect(seeks.append)
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(int(bar.x_of(5000)), 12))
    assert (bar.start, bar.end) == (0, 10_000)
    assert abs(bar.position - 5000) <= 50 and seeks


# -- re-encoding -----------------------------------------------------------------------------------
def test_a_trim_keeps_exactly_the_part_marked_and_can_be_undone(tmp_path):
    video = _grey_clip(tmp_path)
    recorded = video.read_bytes()
    seconds = cliptrim.trim(video, 1000, 2000)
    assert 0.9 <= seconds <= 1.2
    assert cliptrim.is_trimmed(video)
    assert cliptrim.untrimmed_of(video).read_bytes() == recorded
    assert clips.length_of(video.with_suffix(".png")) == pytest.approx(seconds, abs=0.01)
    frames = clips.frames_of(video, fps=30, max_width=10_000)
    assert 12 <= len(frames) <= 18
    # Grey 60 is one second into the recording, 120 two seconds.
    assert 45 <= _grey(frames[0][0]) <= 75
    assert 105 <= _grey(frames[-1][0]) <= 130
    assert not list(tmp_path.glob("*.trimming.mp4"))

    # A second trim starts from the trimmed clip but keeps the recorded one.
    cliptrim.trim(video, 0, 500)
    assert cliptrim.untrimmed_of(video).read_bytes() == recorded

    length = cliptrim.untrim(video)
    assert length > 2.5
    assert video.read_bytes() == recorded and not cliptrim.is_trimmed(video)
    assert clips.length_of(video.with_suffix(".png")) == pytest.approx(length, abs=0.01)


def test_too_little_kept_is_refused(tmp_path):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    with pytest.raises(cliptrim.TrimError):
        cliptrim.trim(video, 1000, 1000 + cliptrim.MIN_KEEP_MS - 1)
    assert video.read_bytes() == b"x" and not cliptrim.is_trimmed(video)


def test_a_missing_clip_is_refused(tmp_path):
    with pytest.raises(cliptrim.TrimError):
        cliptrim.trim(tmp_path / "gone.mp4", 0, 1000)
    with pytest.raises(cliptrim.TrimError):
        cliptrim.untrim(tmp_path / "gone.mp4")


def test_an_unreadable_clip_is_left_alone(tmp_path):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"not a video at all" * 10)
    with pytest.raises(cliptrim.TrimError):
        cliptrim.trim(video, 0, 1000)
    assert video.read_bytes() == b"not a video at all" * 10
    assert not cliptrim.is_trimmed(video) and not list(tmp_path.glob("*.trimming.mp4"))


# -- the player ------------------------------------------------------------------------------------
def test_trimming_from_the_player(tmp_path):
    video = _grey_clip(tmp_path)
    widget = player.ClipPlayer()
    widget.resize(600, 400)
    widget.show()
    widget.load(video, QImage(str(video.with_suffix(".png"))))
    assert widget.btn_trim.isVisible() and not widget.btn_untrim.isVisible()
    widget.begin_trim()
    assert widget.trimming and widget.trim_bar.isVisible() and not widget.slider.isVisible()
    assert not widget.btn_trim_save.isEnabled()      # nothing cut yet
    widget.trim_bar.set_position(1000)
    widget.mark_start()
    widget.trim_bar.set_position(2000)
    widget.mark_end()
    assert (widget.trim_bar.start, widget.trim_bar.end) == (1000, 2000)
    assert widget.btn_trim_save.isEnabled() and "0:01.0 to 0:02.0" in widget.trim_info.text()
    events = []
    widget.about_to_change.connect(lambda path: events.append(("before", path)))
    widget.changed.connect(lambda path: events.append(("after", path)))
    widget.save_trim()
    assert events == [("before", str(video)), ("after", str(video))]
    assert not widget.trimming and widget.video == video
    assert widget.btn_untrim.isVisible()
    assert widget.time.text().endswith("0:01")
    widget.undo_trim()
    assert not widget.btn_untrim.isVisible() and widget.time.text().endswith("0:03")
    widget.close()


def test_cancel_leaves_the_clip_alone(tmp_path):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    widget = player.ClipPlayer()
    widget.load(video, None)
    widget.begin_trim()
    widget.cancel_trim()
    assert not widget.trimming and video.read_bytes() == b"x"


def test_controls_line_up_with_the_window():
    widget = player.ClipPlayer()
    widget.set_control_margins(12, 8, 12, 2)
    assert widget.controls.contentsMargins().left() == 12
    assert widget.trim_row.contentsMargins().right() == 12


def test_buttons_take_the_windows_style():
    assert "QPushButton" not in player.PLAYER_STYLE


# -- lab.md and the app ----------------------------------------------------------------------------
def test_a_trimmed_lab_clip_shows_its_new_length(cfg, tmp_path):
    lab.start(cfg, "Lame")
    cfg["active_lab"] = "Lame"
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    poster = lab.save(clips.make_poster(QImage(32, 32, QImage.Format.Format_RGB32), 23.4), "png", cfg,
                      companion=video)
    assert lab.set_clip_seconds(cfg, poster.name, 7.2)
    index = (lab.active_folder(cfg) / "lab.md").read_text(encoding="utf-8")
    assert "[Video clip, 0:07]" in index
    assert not lab.set_clip_seconds(cfg, "nothing.png", 3)


def test_the_app_updates_lab_md_after_a_trim(cfg, tmp_path, monkeypatch):
    import app as app_mod

    lab.start(cfg, "Lame")
    cfg["active_lab"] = "Lame"
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    poster = lab.save(clips.make_poster(QImage(32, 32, QImage.Format.Format_RGB32), 23.4), "png", cfg,
                      companion=video)
    poster.write_bytes(clips.make_poster(QImage(32, 32, QImage.Format.Format_RGB32), 5.0))
    refreshed = []
    state = SimpleNamespace(cfg=cfg, preview=SimpleNamespace(set_status=lambda text: None),
                            _refresh_menu_text=lambda: refreshed.append("lab"),
                            _refresh_snip_list=lambda: refreshed.append("history"))
    app_mod.ShadowSnipApp._on_clip_trimmed(state, str(poster.with_suffix(".mp4")))
    assert lab.entries(cfg)[-1]["clip_seconds"] == pytest.approx(5.0)
    assert refreshed == ["lab"]
    history = storage.save_history(b"png", "png", cfg)
    app_mod.ShadowSnipApp._on_clip_trimmed(state, str(history.with_suffix(".mp4")))
    assert refreshed == ["lab", "history"]


def test_a_trim_in_the_viewer_lets_go_everywhere_and_reloads(tmp_path):
    import preview

    video = tmp_path / "001.mp4"
    video.write_bytes(b"x")
    poster = video.with_suffix(".png")
    poster.write_bytes(clips.make_poster(QImage(32, 32, QImage.Format.Format_RGB32), 2.0))
    win = preview.PreviewWindow()
    win.show_clip(video, QImage(str(poster)), "Clip saved")
    told = []
    win.clip_changed.connect(told.append)
    win.snips_panel.clip_about_to_change.emit(str(video))
    assert win.player.video is None             # let go, so Windows can replace the file
    win.snips_panel.clip_changed.emit(str(video))
    assert win.player.video == video and told == [str(video)]
    win.close()
