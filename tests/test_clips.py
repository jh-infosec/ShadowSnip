"""Video clips (0.14.0): recording, the poster, filing, lists, GIF export and the controls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QRect, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

import clips
import config
import hotkey_linux
import lab
import recordbar
import recorder
import report
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _frame(colour="#1e2a3a", w=160, h=90) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


# -- the recorder -------------------------------------------------------------------------------
@pytest.mark.parametrize("size, even", [((311, 231), (310, 230)), ((640, 360), (640, 360)), ((1, 1), (2, 2))])
def test_frames_are_made_even(size, even):
    assert recorder.even_size(*size) == even


def test_the_area_goes_to_the_screen_holding_most_of_it():
    from PySide6.QtGui import QGuiApplication

    geom = QGuiApplication.primaryScreen().geometry()
    screen, part = recorder.screen_for(QRect(geom.x() - 50, geom.y() + 10, 200, 100))
    assert screen is QGuiApplication.primaryScreen() and part.left() == geom.x()
    with pytest.raises(recorder.RecorderError):
        recorder.screen_for(QRect(geom.right() + 5000, 0, 10, 10))


class MovingSquare:
    """Stands in for the screen: a square that moves a little every frame."""

    def __init__(self):
        self.n = 0

    def __call__(self, _screen, rect):
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        img.fill(QColor("#101018"))
        p = QPainter(img)
        p.fillRect(QRect(4 + (self.n * 6) % max(1, rect.width() - 30), 20, 24, 24), QColor("#e81123"))
        p.end()
        self.n += 1
        return img


def _record(tmp_path, seconds=1.2, **options) -> tuple[recorder.Recorder, list]:
    from PySide6.QtGui import QGuiApplication

    geom = QGuiApplication.primaryScreen().geometry()
    area = QRect(geom.x(), geom.y(), min(161, geom.width()), min(91, geom.height()))
    rec = recorder.Recorder(area, tmp_path / "clip.mp4", fps=15, grab=MovingSquare(), **options)
    done = []
    loop = QEventLoop()
    rec.finished.connect(lambda path: (done.append(("finished", path)), loop.quit()))
    rec.failed.connect(lambda message: (done.append(("failed", message)), loop.quit()))
    try:
        rec.start()
    except recorder.RecorderError as exc:
        pytest.skip(f"no video encoder here: {exc}")
    QTimer.singleShot(int(seconds * 1000), rec.stop)
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    return rec, done


def test_a_clip_is_recorded_to_mp4(tmp_path):
    rec, done = _record(tmp_path)
    assert done and done[0][0] == "finished", done
    path = Path(done[0][1])
    assert path.is_file() and path.stat().st_size > 0 and path.suffix == ".mp4"
    assert rec.frames_sent >= 5
    assert rec.first_frame.width() % 2 == 0 and rec.first_frame.height() % 2 == 0


def test_a_clip_stops_by_itself_at_its_longest(tmp_path):
    rec, done = _record(tmp_path, seconds=8, max_seconds=1)
    assert done and done[0][0] == "finished"
    assert rec.elapsed() < 2.5


def test_paused_time_is_left_out(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(recorder.time, "monotonic", lambda: clock[0])
    rec = recorder.Recorder.__new__(recorder.Recorder)
    rec._active, rec._run_started = 0.0, 100.0
    clock[0] = 103.0
    assert rec.elapsed() == pytest.approx(3.0)
    rec._active, rec._run_started = rec.elapsed(), None  # what pause() does
    clock[0] = 110.0
    assert rec.elapsed() == pytest.approx(3.0)
    rec._run_started = 110.0  # resume()
    clock[0] = 111.5
    assert rec.elapsed() == pytest.approx(4.5)


# -- the poster and the files -----------------------------------------------------------------
def test_poster_records_the_length_and_finds_its_clip(tmp_path):
    poster = tmp_path / "001_x.png"
    poster.write_bytes(clips.make_poster(_frame(), 83.4))
    assert clips.length_of(poster) == pytest.approx(83.4)
    assert clips.clip_for(poster) is None
    (tmp_path / "001_x.mp4").write_bytes(b"video")
    assert clips.clip_for(poster) == tmp_path / "001_x.mp4"
    assert clips.length_of(tmp_path / "missing.png") is None
    assert clips.clip_for(None) is None


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (23.4, "0:23"), (83, "1:23"), (3725, "1:02:05"), (None, "")])
def test_lengths_read_like_a_player(seconds, text):
    assert clips.format_length(seconds) == text


def test_the_poster_shows_a_play_badge():
    data = clips.make_poster(_frame("#000000", 320, 180), 5)
    poster = QImage.fromData(data)
    assert poster.size().width() == 320
    # Somewhere in the lower left the white triangle of the badge.
    whites = sum(1 for x in range(0, 120) for y in range(100, 180)
                 if QColor(poster.pixel(x, y)).lightness() > 240)
    assert whites > 20


def test_a_clip_is_copied_as_a_file(tmp_path):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    clips.copy_file(video)
    # Read the way it was written (CF_HDROP on Windows): on GitHub's Windows
    # runner Qt's view of the clipboard was still empty at this point.
    # Compared as paths: read back on Windows they come with forward slashes.
    assert [Path(name) for name in _clipboard_files()] == [video]


def test_a_missing_libpulse_is_explained():
    message = clips.multimedia_problem(ImportError("libpulse.so.0: cannot open shared object file"))
    assert "sudo apt install libpulse0" in message
    assert "could not be loaded" in clips.multimedia_problem(ImportError("something else"))


def test_recording_without_qt_multimedia_says_why(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_multimedia(name, *args, **kwargs):
        if name == "PySide6.QtMultimedia":
            raise ImportError("libpulse.so.0: cannot open shared object file")
        return real_import(name, *args, **kwargs)

    rec = recorder.Recorder(QRect(0, 0, 32, 32), Path("x.mp4"))
    monkeypatch.setattr(builtins, "__import__", no_multimedia)
    with pytest.raises(recorder.RecorderError, match="libpulse0"):
        rec.start()


def test_moving_a_poster_takes_its_clip(tmp_path):
    poster, video = tmp_path / "a.png", tmp_path / "a.mp4"
    poster.write_bytes(b"p")
    video.write_bytes(b"v")
    (tmp_path / "bin").mkdir()
    clips.move_with(poster, tmp_path / "bin" / "a_2.png")
    assert (tmp_path / "bin" / "a_2.mp4").read_bytes() == b"v" and not video.exists()


def test_gif_export_from_a_recorded_clip(tmp_path):
    rec, done = _record(tmp_path, seconds=1.5)
    assert done and done[0][0] == "finished"
    seen = []
    frames = clips.export_gif(Path(done[0][1]), tmp_path / "out.gif", progress=lambda s: seen.append(s) or True)
    from PIL import Image

    gif = Image.open(tmp_path / "out.gif")
    assert frames >= 3 and gif.n_frames >= 2 and seen
    assert gif.size[0] <= clips.GIF_MAX_WIDTH


# -- filed like snips ---------------------------------------------------------------------------
@pytest.fixture
def cfg(tmp_path):
    out = dict(config.DEFAULTS)
    out.update(save_dir=str(tmp_path / "snips"), keep_history=True, history_limit=2,
               lab_root=str(tmp_path / "labs"), active_lab="")
    return out


def _clip_file(tmp_path, name="rec.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return video


def test_history_files_the_clip_beside_its_poster_and_never_prunes_it(cfg, tmp_path):
    poster = clips.make_poster(_frame(), 4)
    first = storage.save_history(poster, "png", cfg, companion=_clip_file(tmp_path))
    assert first.with_suffix(".mp4").is_file()
    for _ in range(4):
        storage.save_history(b"\x89PNG\r\n\x1a\n" + b"0" * 10, "png", cfg)
    assert first.is_file() and first.with_suffix(".mp4").is_file()  # older than the limit, kept


def test_history_removal_moves_the_clip_too(cfg, tmp_path):
    poster = storage.save_history(clips.make_poster(_frame(), 4), "png", cfg, companion=_clip_file(tmp_path))
    moved = storage.remove_from_history(cfg, poster.name)
    assert moved.with_suffix(".mp4").is_file() and not poster.with_suffix(".mp4").exists()


def test_a_lab_files_and_links_the_clip(cfg, tmp_path):
    lab.start(cfg, "Lame")
    cfg["active_lab"] = "Lame"
    poster = lab.save(clips.make_poster(_frame(), 23.4), "png", cfg, companion=_clip_file(tmp_path))
    assert poster.with_suffix(".mp4").is_file()
    entry = lab.entries(cfg)[-1]
    assert entry["clip"] == poster.with_suffix(".mp4").name and entry["clip_seconds"] == pytest.approx(23.4)
    index = (lab.active_folder(cfg) / "lab.md").read_text(encoding="utf-8")
    assert f"[Video clip, 0:23]({poster.with_suffix('.mp4').name})" in index
    removed = lab.remove_snip(cfg, poster.name)
    assert removed and not poster.with_suffix(".mp4").exists()
    assert list((lab.active_folder(cfg) / lab.REMOVED_DIR).glob("*.mp4"))


def test_lab_md_never_links_a_clip_outside_the_folder():
    entry = {"kind": "snip", "file": "001_a.png", "number": 1, "clip": "../../evil.mp4"}
    text = "\n".join(lab._render_snip(entry, []))
    assert "evil" not in text


def test_reports_name_the_clip_in_the_caption(tmp_path):
    poster = tmp_path / "001_a.png"
    poster.write_bytes(clips.make_poster(_frame(), 61))
    assert report._clip_line({"path": str(poster)}) == ""
    (tmp_path / "001_a.mp4").write_bytes(b"v")
    assert report._clip_line({"path": str(poster)}) == "Video clip 001_a.mp4 (1:01), in the lab folder"


# -- the snip list ------------------------------------------------------------------------------
@pytest.fixture
def panel(cfg, tmp_path):
    import labsnips

    storage.save_history(clips.make_poster(_frame(), 7), "png", cfg, companion=_clip_file(tmp_path))
    widget = labsnips.LabSnipsPanel()
    widget.set_lab_mode(False)
    rows = storage.history_rows(cfg)
    widget.set_rows(rows, rows[-1]["file"])
    widget.show()
    yield widget
    widget.close()


def test_a_clip_row_says_it_plays(panel):
    import labsnips as ls

    assert panel.list.topLevelItem(0).text(ls.COL_MARKS).startswith("▶ 0:07")
    assert panel.selected_clip() is not None
    assert panel.btn_expand.text() == "Play"


def test_a_clips_menu_plays_and_offers_a_gif(panel):
    texts = [a.text() for a in panel.snip_menu().actions() if not a.isSeparator()]
    assert texts[:2] == ["Play", "Play in video player"] and "Save as GIF..." in texts


def test_opening_a_clip_plays_it(panel, monkeypatch):
    import player

    opened = []
    monkeypatch.setattr(storage, "open_file", opened.append)
    panel._emit_open()
    panel.clip_play_mode = player.PLAY_EXTERNAL
    panel.expand()
    assert opened == [panel.selected_clip(), panel.selected_clip()]


def test_copying_a_clip_copies_the_video(panel):
    asked = []
    panel.copy_requested.connect(asked.append)
    panel.copy_selected()
    assert asked == []  # not the poster image
    assert _clipboard_files()[0].endswith(".mp4")


def _clipboard_files() -> list[str]:
    """The files on the clipboard.

    On Windows they are read the way they were written, straight from the
    Windows clipboard: Qt's own view of it catches up a moment later, so
    asking Qt straight away sometimes found it empty.
    """
    import sys

    if sys.platform == "win32":
        try:
            import win32clipboard as clip
            import win32con
        except ImportError:
            pass
        else:
            import clipboard

            clipboard._open_with_retry(clip)
            try:
                return list(clip.GetClipboardData(win32con.CF_HDROP))
            finally:
                clip.CloseClipboard()
    return [url.toLocalFile() for url in QApplication.clipboard().mimeData().urls()]


# -- the controls and the app -------------------------------------------------------------------
def test_the_bar_goes_below_then_above_then_inside():
    screen = QRect(0, 0, 1000, 800)
    from PySide6.QtCore import QSize

    size = QSize(200, 40)
    assert recordbar.bar_place(QRect(100, 100, 300, 200), size, screen).y() > 300
    assert recordbar.bar_place(QRect(100, 500, 300, 290), size, screen).y() < 500
    inside = recordbar.bar_place(QRect(0, 0, 1000, 800), size, screen)
    assert 0 <= inside.y() < 800


def test_the_frame_sits_just_outside_the_area():
    area = QRect(100, 100, 300, 200)
    for edge in recordbar.frame_edges(area):
        inner = edge.intersected(area)
        assert inner.isEmpty()


def test_the_bar_never_takes_focus():
    from PySide6.QtCore import Qt

    bar = recordbar.RecordingBar(microphone=True)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert bar.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert not bar.mic.isHidden()
    bar.show_seconds(65)
    assert bar.time.text() == "1:05"
    bar.close()


def test_snipping_waits_while_a_clip_records():
    import app as app_mod

    said = []
    state = SimpleNamespace(recorder=object(), busy=False,
                            toast=SimpleNamespace(show_message=said.append))
    app_mod.ShadowSnipApp.request_snip(state)
    assert said and "stop it first" in said[0] and state.busy is False


def test_the_clip_hotkey_stops_a_clip_running():
    import app as app_mod

    stopped = []
    state = SimpleNamespace(recorder=object(), stop_recording=lambda: stopped.append(True))
    app_mod.ShadowSnipApp.request_record(state)
    assert stopped == [True]


def test_a_clip_with_nowhere_else_goes_to_a_clips_folder(cfg, tmp_path):
    import app as app_mod

    cfg["keep_history"] = False
    state = SimpleNamespace(cfg=cfg)
    saved = app_mod.ShadowSnipApp._save_clip(state, _clip_file(tmp_path), _frame(), 3)
    assert saved.parent.name == "clips" and saved.is_file() and saved.with_suffix(".png").is_file()


def test_clip_settings_and_hotkey():
    cfg = config._sanitise({**dict(config.DEFAULTS), "clip_fps": 24, "clip_max_minutes": 999,
                            "clip_microphone": 1, "record_hotkey": ""})
    assert cfg["clip_fps"] == 15 and cfg["clip_max_minutes"] == 60 and cfg["clip_microphone"] is True
    assert cfg["record_hotkey"] == config.DEFAULTS["record_hotkey"] == "ctrl+alt+r"
    assert config.DEFAULTS["clip_microphone"] is False
    assert hotkey_linux.ACTION_FLAGS["record"] == "--record"


def test_settings_carry_the_clip_options():
    import settings_dialog

    dialog = settings_dialog.SettingsDialog(dict(config.DEFAULTS))
    dialog.clip_mic_check.setChecked(True)
    dialog.clip_fps_combo.setCurrentIndex(dialog.clip_fps_combo.findData(30))
    values = dialog.values()
    assert values["clip_microphone"] is True and values["clip_fps"] == 30
    assert values["record_hotkey"] == "ctrl+alt+r"
    dialog.close()


def test_the_windows_file_drop_block_is_laid_out_like_explorers():
    import struct

    import clipboard

    data = clipboard.drop_files_data([r"C:\labs\Lame\001_a.mp4", r"C:\x.mp4"])
    offset, _x, _y, _nc, wide = struct.unpack("<IiiII", data[:20])
    assert offset == 20 and wide == 1
    names = data[20:].decode("utf-16-le")
    assert names == "C:\\labs\\Lame\\001_a.mp4\0C:\\x.mp4\0\0"


# -- the encoder's start-up (0.14.0) ------------------------------------------------------------
class SlowInput:
    """An encoder that refuses frames until it has been offered `refuse` of them."""

    def __init__(self, refuse):
        self.refuse, self.offers, self.taken = refuse, 0, []

    def sendVideoFrame(self, frame):
        self.offers += 1
        if self.offers <= self.refuse:
            return False
        self.taken.append(frame.startTime())
        return True


def _warming(refuse, monkeypatch, clock):
    from PySide6.QtCore import QObject

    monkeypatch.setattr(recorder.time, "monotonic", lambda: clock[0])
    rec = recorder.Recorder.__new__(recorder.Recorder)
    QObject.__init__(rec)
    stops = []
    rec.fps, rec.max_seconds, rec.first_frame = 15, 600, _frame()
    rec._input = SlowInput(refuse)
    rec._recorder = SimpleNamespace(stop=lambda: stops.append(True))
    rec._timer = SimpleNamespace(stop=lambda: None, start=lambda: None)
    rec._grab = lambda screen, rect: _frame()
    rec.screen, rec.rect = None, QRect(0, 0, 160, 90)
    from PySide6.QtCore import QSize

    rec._size = QSize(160, 90)
    rec.frames_sent = rec.frames_dropped = 0
    rec.paused = rec._started = rec._stopping = rec._stop_wanted = rec._failed = False
    rec._active, rec._run_started, rec._last_tick, rec._warm_from = 0.0, None, -1, clock[0]
    return rec, stops


def test_the_first_frame_waits_for_a_slow_encoder(monkeypatch):
    clock = [50.0]
    rec, _stops = _warming(3, monkeypatch, clock)
    begun = []
    rec.started.connect(lambda: begun.append(True))
    for _ in range(3):
        clock[0] += 0.5
        rec._frame()
    assert not rec.is_started and rec.frames_dropped == 0 and rec.elapsed() == 0
    clock[0] += 0.5
    rec._frame()
    assert rec.is_started and begun == [True]
    assert rec._input.taken == [0]          # the clip starts at zero, not at 2 seconds
    clock[0] += 1.0
    rec._frame()
    assert rec._input.taken[1] == pytest.approx(1_000_000)


def test_stop_during_start_up_waits_for_the_first_frame(monkeypatch):
    clock = [50.0]
    rec, stops = _warming(2, monkeypatch, clock)
    rec._offer_first()
    rec.stop()
    assert stops == [] and rec.recording          # not stopped empty
    rec._frame()
    assert stops == []
    rec._frame()                                  # the encoder takes it: now it stops
    assert stops == [True] and rec.frames_sent == 1


def test_an_encoder_that_never_starts_is_a_failure_not_an_empty_clip(monkeypatch):
    clock = [50.0]
    rec, stops = _warming(10_000, monkeypatch, clock)
    said, done = [], []
    rec.failed.connect(said.append)
    rec.finished.connect(done.append)
    rec._frame()
    clock[0] += recorder.WARMUP_SECONDS + 1
    rec._frame()
    assert said == ["The video encoder did not start. Nothing was recorded."]
    assert stops == [True] and not rec.recording
    rec._on_state(None)
    assert done == []


def test_pause_is_ignored_until_the_clip_has_started(monkeypatch):
    rec, _stops = _warming(5, monkeypatch, [50.0])
    rec.pause()
    assert rec.paused is False


# -- file writes on Windows (0.14.0) ------------------------------------------------------------
def test_a_file_held_for_a_moment_is_still_replaced():
    calls, waits = [], []

    def replace(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise PermissionError("in use")

    storage.replace_with_retry("a", "b", replace=replace, sleep=waits.append)
    assert len(calls) == 3 and len(waits) == 2


def test_a_file_held_for_good_still_fails():
    def replace(source, target):
        raise PermissionError("in use")

    with pytest.raises(PermissionError):
        storage.replace_with_retry("a", "b", attempts=3, replace=replace, sleep=lambda s: None)
