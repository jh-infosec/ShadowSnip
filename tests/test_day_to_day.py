"""0.19.0, faster day to day: Copy as, the recent strip, and marks on clips."""

from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QRect, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import app as app_mod
import clipboard
import clipmarks
import clips
import cliptrim
import config
import copyas
import lab
import platforms
import recentstrip
from annotate import AnnotationDoc, Mark, Redact


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _picture(colour=(40, 120, 200), size=(320, 200)) -> Image.Image:
    image = Image.new("RGB", size, colour)
    for x in range(0, size[0], 8):   # some detail, so the formats differ in size
        for y in range(0, size[1], 8):
            image.putpixel((x, y), (x % 256, y % 256, 90))
    return image


# -- Copy as ----------------------------------------------------------------------------------------
def test_every_format_has_a_label():
    assert [fmt for fmt, _ in copyas.FORMATS] == ["png", "jpeg", "webp", "data_uri", "markdown"]


@pytest.mark.parametrize("fmt, kind", [("jpeg", "JPEG"), ("webp", "WEBP"), ("png", "PNG")])
def test_encoding_makes_that_format(fmt, kind):
    data = copyas.encode(_picture(), fmt)
    assert Image.open(io.BytesIO(data)).format == kind


def test_a_transparent_snip_becomes_a_jpeg_on_white():
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    out = Image.open(io.BytesIO(copyas.encode(image, "jpeg")))
    assert out.mode == "RGB" and min(out.getpixel((20, 20))) > 240


def test_a_data_uri_is_the_png_as_text():
    png = copyas.encode(_picture(), "png")
    message = copyas.copy("data_uri", _picture(), png=png)
    text = QApplication.clipboard().text()
    assert text.startswith("data:image/png;base64,")
    assert base64.b64decode(text.split(",", 1)[1]) == png
    assert "data URI" in message


def test_a_markdown_image_carries_the_caption():
    copyas.copy("markdown", _picture(), caption="smb [anon] share")
    text = QApplication.clipboard().text()
    assert text.startswith("![smb (anon) share](data:image/png;base64,")


def test_jpeg_and_webp_go_on_as_small_files(tmp_path):
    for fmt, suffix in (("jpeg", ".jpg"), ("webp", ".webp")):
        message = copyas.copy(fmt, _picture(), folder=tmp_path / "copies", name="004_2026-11-24_10-00-00")
        written = tmp_path / "copies" / f"004_2026-11-24_10-00-00{suffix}"
        assert written.is_file() and written.name in message
        assert [Path(name) for name in _clipboard_files()] == [written]


def _clipboard_files() -> list[str]:
    """The files on the clipboard, read on Windows the way copyas wrote them (CF_HDROP).

    Qt's view of the Windows clipboard catches up a moment later: on GitHub's
    Windows runner it was still empty here.
    """
    if sys.platform == "win32":
        try:
            import win32clipboard as clip
            import win32con
        except ImportError:
            pass
        else:
            clipboard._open_with_retry(clip)
            try:
                return list(clip.GetClipboardData(win32con.CF_HDROP))
            finally:
                clip.CloseClipboard()
    return [u.toLocalFile() for u in QApplication.clipboard().mimeData().urls()]


def test_the_copies_folder_keeps_only_the_newest(tmp_path):
    folder = tmp_path / "copies"
    import os

    for index in range(copyas.KEEP + 4):
        path = copyas.write_copy(folder, f"snip{index}", b"x", "jpg")
        assert path.is_file()   # never the file just written
        stamp = time.time() + index
        os.utime(path, (stamp, stamp))
    copyas.prune(folder)
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == copyas.KEEP and "snip0.jpg" not in names


def test_a_file_name_is_made_safe():
    assert copyas.safe_name("../a b:c") == "a_b_c"
    assert copyas.safe_name("") == "snip"


def test_png_is_the_usual_copy(monkeypatch):
    seen = []
    monkeypatch.setattr(clipboard, "copy", lambda png, image, include_dib=True: seen.append((png, include_dib)))
    copyas.copy("png", _picture(), png=b"PNGDATA", include_dib=False)
    assert seen == [(b"PNGDATA", False)]


def test_the_snip_right_click_menu_offers_copy_as():
    from annotate import AnnotCanvas

    canvas = AnnotCanvas()
    image = QImage(100, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    canvas.resize(300, 200)
    canvas.show()
    canvas.load(image)
    QApplication.processEvents()
    where = canvas._target().center()
    asked = []
    canvas.copy_as_requested.connect(asked.append)
    rows = canvas.context_actions(where)
    submenu = next(row for row in rows if row and row[0] == "Copy as")[1]
    assert [label for label, _cb, _s in submenu] == [label for _f, label in copyas.FORMATS]
    submenu[1][1]()
    assert asked == ["jpeg"]
    canvas.offer_copy_as = False
    assert not any(row and row[0] == "Copy as" for row in canvas.context_actions(where))
    canvas.close()


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(qapp)
    s.cfg["save_dir"] = str(tmp_path / "snips")
    yield s
    s.autocopy.release()
    s.preview.close()
    s.tray.hide()


def _snip(s, colour=(10, 90, 10)):
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(*colour))
    s._handle_snip(image)


def test_the_snip_on_screen_copies_as_webp_into_the_copies_folder(shadow, tmp_path):
    s = shadow
    lab.start(s.cfg, "box")
    s.cfg["active_lab"] = "box"
    _snip(s)
    s.preview.copy_image_as("webp")
    copies = list((tmp_path / "snips" / "copies").glob("*.webp"))
    assert len(copies) == 1 and copies[0].stem == Path(s._last_lab_file).stem
    assert "WebP" in s.preview.status.text()


def test_a_listed_snip_copies_as_a_data_uri(shadow):
    s = shadow
    lab.start(s.cfg, "box")
    s.cfg["active_lab"] = "box"
    _snip(s)
    _snip(s, (200, 20, 20))
    first = lab.snip_rows(s.cfg)[0]["file"]
    s.preview.snips_panel.select(first)
    s.preview.snips_panel.copy_selected_as("data_uri")
    data = base64.b64decode(QApplication.clipboard().text().split(",", 1)[1])
    assert Image.open(io.BytesIO(data)).convert("RGB").getpixel((5, 5)) == (10, 90, 10)
    assert s.preview.status.text().startswith("Snip 001: Copied as a data URI")


def test_an_encrypted_labs_copy_goes_to_its_private_folder(shadow, tmp_path):
    import vault

    s = shadow
    folder = lab.start(s.cfg, "secret")
    vault.create(folder, "correct horse battery")
    s.cfg["active_lab"] = "secret"
    try:
        assert s._copies_folder() == vault.vault_for(folder).handoff_dir()
        assert not str(s._copies_folder()).startswith(str(tmp_path / "snips"))
    finally:
        vault.lock_all()


# -- the recent strip -----------------------------------------------------------------------------
def _rows(folder: Path, count: int) -> list[dict]:
    rows = []
    for number in range(1, count + 1):
        path = folder / f"{number:03d}_snip.png"
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        image.fill(QColor(number * 10, 50, 50))
        image.save(str(path))
        rows.append({"file": path.name, "number": number, "path": str(path), "caption": f"cap {number}"})
    return rows


def test_the_strip_shows_the_newest_first(tmp_path):
    strip = recentstrip.RecentStrip()
    strip.set_rows(_rows(tmp_path, 12))
    assert strip.files() == [f"{n:03d}_snip.png" for n in range(12, 12 - recentstrip.COUNT, -1)]
    assert not strip.tiles[0].icon().isNull()
    assert "Snip 012" in strip.tiles[0].toolTip() and "cap 12" in strip.tiles[0].toolTip()


def test_a_click_asks_to_copy_and_a_double_click_to_open(tmp_path):
    strip = recentstrip.RecentStrip()
    strip.set_rows(_rows(tmp_path, 3))
    copied, opened = [], []
    strip.copy_requested.connect(copied.append)
    strip.expand_requested.connect(opened.append)
    strip.tiles[1].click()
    strip.tiles[0].double_clicked.emit(strip.tiles[0].filename)
    assert copied == ["002_snip.png"] and opened == ["003_snip.png"]


def test_the_strip_can_be_turned_off_and_hides_when_empty(tmp_path):
    strip = recentstrip.RecentStrip()
    strip.show()
    strip.set_rows(_rows(tmp_path, 2))
    assert strip.isVisible()
    strip.set_wanted(False)
    assert not strip.isVisible()
    strip.set_wanted(True)
    strip.clear()
    assert not strip.isVisible()


def test_the_strip_menu_has_copy_as_for_a_snip(tmp_path, monkeypatch):
    strip = recentstrip.RecentStrip()
    strip.set_rows(_rows(tmp_path, 1))
    shown = []
    monkeypatch.setattr(strip, "_popup", lambda menu, where: shown.append(menu))
    asked = []
    strip.copy_as_requested.connect(lambda f, fmt: asked.append((f, fmt)))
    strip._menu(strip.tiles[0], strip.tiles[0].rect().center())
    texts = [a.text() for a in shown[0].actions()]
    assert texts == ["Copy", "Copy as", "Expand"]
    shown[0].actions()[1].menu().actions()[2].trigger()
    assert asked == [("001_snip.png", "webp")]


def test_a_click_in_the_window_strip_copies_like_the_list(shadow):
    s = shadow
    lab.start(s.cfg, "box")
    s.cfg["active_lab"] = "box"
    for colour in ((1, 1, 1), (2, 2, 2), (3, 3, 3)):
        _snip(s, colour)
    strip = s.preview.recent
    assert strip.files()[0] == s._last_lab_file and len(strip.files()) == 3
    asked = []
    s.preview.snip_copy_requested.connect(asked.append)
    strip.tiles[2].click()
    assert asked == [lab.snip_rows(s.cfg)[0]["file"]]
    assert s.preview.selected_snip() == asked[0]


def test_locking_the_lab_empties_the_strip(shadow):
    s = shadow
    lab.start(s.cfg, "box")
    s.cfg["active_lab"] = "box"
    _snip(s)
    assert s.preview.recent.files()
    s.preview.hide_for_lock()
    assert s.preview.recent.files() == []


def test_settings_turn_the_strip_off(shadow):
    s = shadow
    s.preview.set_recent_strip(False)
    assert not s.preview.recent._wanted
    assert config.DEFAULTS["recent_strip"] is True


# -- marks on clips -----------------------------------------------------------------------------------
def _doc_with_box(size=(160, 90)) -> AnnotationDoc:
    base = QImage(*size, QImage.Format.Format_RGB32)
    base.fill(QColor("black"))
    doc = AnnotationDoc(base)
    doc.add(Mark(doc.new_id(), "rect", "#ff0000", QPointF(20, 20), QPointF(60, 60), width=6.0))
    return doc


def _red_at(image: QImage, x: int, y: int) -> bool:
    colour = image.pixelColor(x, y)
    return colour.red() > 180 and colour.green() < 80


def test_the_overlay_draws_the_marks_on_each_frame():
    transform = clipmarks.overlay(_doc_with_box())
    frame = QImage(160, 90, QImage.Format.Format_RGB32)
    frame.fill(QColor(0, 200, 0))
    out = transform(frame, 500)
    assert _red_at(out, 20, 40)              # on the box's edge
    assert out.pixelColor(100, 80).green() > 180   # the frame itself, elsewhere


def test_the_overlay_waits_for_its_moment():
    transform = clipmarks.overlay(_doc_with_box(), from_ms=1000)
    frame = QImage(160, 90, QImage.Format.Format_RGB32)
    frame.fill(QColor(0, 200, 0))
    assert not _red_at(transform(frame, 999), 20, 40)
    assert _red_at(transform(frame, 1000), 20, 40)


def test_a_redaction_blurs_each_frame_not_the_first():
    base = QImage(80, 80, QImage.Format.Format_RGB32)
    base.fill(QColor("white"))
    doc = AnnotationDoc(base)
    doc.add(Redact(doc.new_id(), QRect(0, 0, 40, 40), "black"))
    frame = QImage(80, 80, QImage.Format.Format_RGB32)
    frame.fill(QColor(0, 0, 255))
    out = clipmarks.overlay(doc)(frame, 0)
    assert out.pixelColor(10, 10).lightness() < 20 and out.pixelColor(60, 60).blue() > 200


def test_nothing_drawn_is_nothing_to_save():
    base = QImage(40, 40, QImage.Format.Format_RGB32)
    assert not clipmarks.has_marks(AnnotationDoc(base))
    assert not clipmarks.has_marks(None)
    assert clipmarks.has_marks(_doc_with_box())


def test_the_markup_window_leaves_out_crop_and_text():
    frame = QImage(160, 90, QImage.Format.Format_RGB32)
    frame.fill(QColor("grey"))
    dialog = clipmarks.ClipMarkupDialog(frame, 1500, "0:03", "0:01.5")
    for kind in clipmarks.LEFT_OUT:
        assert dialog.tools.buttons[kind].isHidden()
    assert dialog.tools.btn_quick.isHidden()
    assert not dialog.btn_save.isEnabled()
    assert dialog.when.count() == 2 and dialog.when.itemData(1) == 1500
    dialog.canvas.doc.add(Mark(dialog.canvas.doc.new_id(), "rect", "#ff0000", QPointF(5, 5), QPointF(50, 50),
                               width=4.0))
    dialog.canvas.edited.emit()
    assert dialog.btn_save.isEnabled()
    dialog.when.setCurrentIndex(1)
    assert dialog.from_ms() == 1500
    assert clipmarks.ClipMarkupDialog(frame, 0, "0:03", "0:00").when.count() == 1


def _wait(predicate, ms=15000) -> bool:
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(20)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return bool(predicate())


def _green_clip(folder: Path, seconds=2.0) -> Path:
    import recorder
    from PySide6.QtGui import QGuiApplication

    def grab(_screen, rect):
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        img.fill(QColor(0, 200, 0))
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


def test_marks_go_on_every_frame_and_come_off_again(tmp_path):
    video = _green_clip(tmp_path)
    recorded = video.read_bytes()
    seconds = cliptrim.mark(video, clipmarks.overlay(_doc_with_box()), 2000)
    assert seconds > 1.5
    frames = clips.frames_of(video, fps=10, max_width=10_000)
    assert len(frames) >= 10
    assert all(_red_at(image, 20, 40) for image, _at in frames)
    assert all(image.pixelColor(120, 75).green() > 150 for image, _at in frames)
    assert cliptrim.untrimmed_of(video).read_bytes() == recorded
    cliptrim.untrim(video)
    assert video.read_bytes() == recorded


def test_mark_up_from_the_player(tmp_path, monkeypatch):
    import player

    video = _green_clip(tmp_path)
    widget = player.ClipPlayer()
    widget.load(video)
    seen = {}

    class StandIn:
        def __init__(self, frame, at_ms):
            seen["frame"], seen["at"] = frame, at_ms

        def exec(self):
            return True

        def has_marks(self):
            return True

        def transform(self):
            return clipmarks.overlay(_doc_with_box(), from_ms=0)

    monkeypatch.setattr(widget, "_markup_dialog", lambda frame, at_ms: StandIn(frame, at_ms))
    changed = []
    widget.changed.connect(changed.append)
    widget.begin_markup()
    assert seen["frame"].width() == 160 and seen["at"] == 0
    assert changed == [str(video)]
    assert widget.btn_untrim.isVisibleTo(widget) and widget.btn_untrim.text() == "As recorded"
    frames = clips.frames_of(video, fps=5, max_width=10_000)
    assert frames and _red_at(frames[-1][0], 20, 40)
