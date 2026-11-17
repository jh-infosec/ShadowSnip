"""Playing clips inside ShadowSnip (0.14.1): the player, the main window, the viewer, the app."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import clips
import config
import player
import recorder
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _frame(colour="#1e2a3a", w=160, h=90) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


@pytest.fixture
def cfg(tmp_path):
    out = dict(config.DEFAULTS)
    out.update(save_dir=str(tmp_path / "snips"), keep_history=True, history_limit=20,
               lab_root=str(tmp_path / "labs"), active_lab="")
    return out


def _wait(predicate, ms=8000) -> bool:
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(20)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return bool(predicate())


def _recorded(tmp_path, seconds=1.0) -> Path:
    """A real clip of a colour that changes every frame, or skip without an encoder."""
    from PySide6.QtGui import QGuiApplication

    n = [0]

    def grab(_screen, rect):
        n[0] += 1
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        img.fill(QColor(40 + (n[0] * 9) % 200, 20, 60))
        return img

    geom = QGuiApplication.primaryScreen().geometry()
    rec = recorder.Recorder(QRect(geom.x(), geom.y(), 160, 90), tmp_path / "rec.mp4", fps=15, grab=grab)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append(None))
    try:
        rec.start()
    except recorder.RecorderError as exc:
        pytest.skip(f"no video encoder here: {exc}")
    QTimer.singleShot(int(seconds * 1000), rec.stop)
    _wait(lambda: bool(done), 15000)
    if not done or done[0] is None:
        pytest.skip("this machine's encoder recorded nothing")
    return Path(done[0])


# -- the player ------------------------------------------------------------------------------------
@pytest.mark.parametrize("picture, box, expect", [
    ((200, 100), (400, 400), (0, 100, 400, 200)),
    ((100, 200), (400, 400), (100, 0, 200, 400)),
    ((10, 10), (400, 400), (190, 190, 20, 20)),     # never more than twice its size
])
def test_a_frame_fits_its_box(picture, box, expect):
    rect = player.fit_rect(QSize(*picture), QSize(*box))
    assert (round(rect.x()), round(rect.y()), round(rect.width()), round(rect.height())) == expect


def test_the_poster_shows_until_it_plays(tmp_path):
    poster_path = tmp_path / "a.png"
    poster_path.write_bytes(clips.make_poster(_frame(), 23))
    video = tmp_path / "a.mp4"
    video.write_bytes(b"\x00")
    widget = player.ClipPlayer()
    widget.load(video, QImage(str(poster_path)))
    assert widget.screen_area.picture is not None
    assert widget.time.text() == "0:00 / 0:23" and widget.btn_play.text() == "Play"
    widget.unload()
    assert widget.video is None and widget.screen_area.picture is None


def test_a_clip_plays_to_the_end_and_back_to_play(tmp_path):
    video = _recorded(tmp_path)
    widget = player.ClipPlayer()
    widget.resize(320, 240)
    widget.show()
    widget.load(video, _frame("#000000"))
    pictures = []
    widget.screen_area.show_picture = lambda image, _orig=widget.screen_area.show_picture: (
        pictures.append(image.pixelColor(5, 5).red() if image is not None else None), _orig(image))
    widget.play()
    assert _wait(lambda: widget.btn_play.text() == "Pause", 5000)
    assert _wait(lambda: widget._at_end, 10000)
    assert widget.btn_play.text() == "Play"
    assert len({p for p in pictures if p is not None}) >= 3     # the picture moved
    widget.unload()
    widget.close()


def test_playing_a_missing_clip_says_so(tmp_path):
    widget = player.ClipPlayer()
    widget.load(tmp_path / "gone.mp4", None)
    widget.play()
    assert "no longer there" in widget.screen_area.message


def test_open_in_video_player(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(storage, "open_file", opened.append)
    widget = player.ClipPlayer()
    widget.load(tmp_path / "a.mp4", None)
    widget.open_external()
    assert opened == [tmp_path / "a.mp4"]


# -- the main window -------------------------------------------------------------------------------
@pytest.fixture
def window():
    import preview

    win = preview.PreviewWindow()
    yield win
    win.close()


def test_a_recorded_clip_takes_the_snips_place(window, tmp_path, monkeypatch):
    video = tmp_path / "001.mp4"
    video.write_bytes(b"\x00")
    window.show_snip(_frame(), b"png", "png", None, "snip", lambda: None)
    assert window.view.currentWidget() is window.canvas
    window.show_clip(video, _frame("#336699"), "Clip saved")
    assert window.view.currentWidget() is window.player
    assert window.showing_clip() == video
    assert not window.tools._available and not window.tools.btn_stamp.isEnabled()
    assert window.btn_copy.text() == "Copy clip"
    copied = []
    monkeypatch.setattr(clips, "copy_file", copied.append)
    window.copy_image()
    assert copied == [video]
    # The next snip puts the canvas back.
    window.show_snip(_frame(), b"png", "png", None, "snip", lambda: None)
    assert window.view.currentWidget() is window.canvas and window.showing_clip() is None
    assert window.btn_copy.text() == "Copy again"


def test_removing_the_clip_on_screen_lets_go_of_it(window, tmp_path):
    video = tmp_path / "001.mp4"
    video.write_bytes(b"\x00")
    window.show_clip(video, _frame(), "Clip saved")
    window.let_go_of_files(["other.png"])
    assert window.player.video == video
    window.let_go_of_files(["001.png"])
    assert window.player.video is None
    window.forget_snip_on_screen()
    assert window.view.currentWidget() is window.canvas


# -- the full-size view ----------------------------------------------------------------------------
def test_the_viewer_plays_a_clip_and_shows_a_snip(cfg, tmp_path):
    import labsnips

    video = tmp_path / "rec.mp4"
    video.write_bytes(b"\x00")
    storage.save_history(_png(), "png", cfg)
    clip_poster = storage.save_history(clips.make_poster(_frame(), 5), "png", cfg, companion=video)
    panel = labsnips.LabSnipsPanel()
    panel.set_lab_mode(False)
    rows = storage.history_rows(cfg)
    panel.set_rows(rows, clip_poster.name)
    assert panel.selected() == clip_poster.name
    panel.expand()
    viewer = panel.viewer
    assert viewer.view.currentWidget() is viewer.player
    assert viewer.player.video == clip_poster.with_suffix(".mp4")
    assert viewer.btn_copy.isEnabled() and not viewer.tools._available
    viewer.step(-1)
    assert viewer.view.currentWidget() is viewer.canvas and viewer.player.video is None
    viewer.step(1)
    viewer.let_go_of([clip_poster.name])
    assert viewer.player.video is None
    viewer.close()
    panel.close()


def _png() -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    _frame("#884422").save(buf, "PNG")
    return bytes(data.data())


# -- the app ---------------------------------------------------------------------------------------
def test_a_finished_clip_is_shown_and_picked_out_in_the_list(cfg, tmp_path, monkeypatch):
    import app as app_mod

    monkeypatch.setattr(clips, "copy_file", lambda path: None)
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    shown, refreshed = [], []
    state = SimpleNamespace(
        cfg=cfg, recorder=SimpleNamespace(first_frame=_frame(), elapsed=lambda: 4.0),
        _end_recording_ui=lambda: None, _finish_busy=lambda: None,
        toast=SimpleNamespace(show_message=lambda text: None),
        preview=SimpleNamespace(show_clip=lambda *a, **k: shown.append((a, k))),
        _refresh_snip_list=lambda: refreshed.append(state._last_history_file),
        _refresh_menu_text=lambda: None, _last_lab_file="old.png", _last_history_file="old.png",
        _snip_paths={"history": Path("old.png")},
    )
    state._save_clip = lambda v, f, s: app_mod.ShadowSnipApp._save_clip(state, v, f, s)
    app_mod.ShadowSnipApp._on_record_finished(state, str(video))
    poster = Path(shown[0][0][0]).with_suffix(".png")
    assert poster.is_file() and Path(shown[0][0][0]).suffix == ".mp4"
    assert state._last_history_file == poster.name and refreshed == [poster.name]
    assert state._last_lab_file == "" and state._snip_paths == {}


def test_where_clips_play_is_a_setting():
    cfg = config._sanitise({**dict(config.DEFAULTS), "clip_player": "vlc"})
    assert cfg["clip_player"] == "app"
    cfg = config._sanitise({**dict(config.DEFAULTS), "clip_player": "external"})
    assert cfg["clip_player"] == "external"


def test_settings_offer_where_clips_play():
    import settings_dialog

    cfg = config._sanitise({**dict(config.DEFAULTS), "clip_player": "external"})
    dialog = settings_dialog.SettingsDialog(cfg)
    assert dialog.clip_player_combo.currentData() == "external"
    dialog.clip_player_combo.setCurrentIndex(dialog.clip_player_combo.findData("app"))
    assert dialog.values()["clip_player"] == "app"
    dialog.close()
