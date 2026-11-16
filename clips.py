"""Video clips as files (0.14.0): the poster beside each MP4, GIF export, copying.

A clip is saved as two files with the same name:

    004_2026-11-16_11-30-00.mp4   the video
    004_2026-11-16_11-30-00.png   its poster: the first frame, with a play
                                  badge and the clip's length drawn on it

The poster is an ordinary snip image, so every list, lab.md, the HTML and
Word reports and the full-size view show a clip without knowing about video.
The places where a clip behaves differently (play, copy, save as GIF, remove)
find the video with `clip_for()`: the .mp4 of the same name beside the image.

The poster also carries the clip's length in a PNG text chunk, so a list can
show "0:23" without opening the video.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPolygonF

SUFFIX = ".mp4"
POSTER_KEY = "ShadowSnip-Clip-Seconds"
# GIF export: wider frames are scaled down to this, and longer clips are cut.
GIF_MAX_WIDTH = 800
GIF_FPS = 10
GIF_MAX_SECONDS = 60


def clip_for(image_path) -> Path | None:
    """The clip a poster stands for: the .mp4 of the same name beside it, or None."""
    if not image_path:
        return None
    path = Path(image_path)
    video = path.with_suffix(SUFFIX)
    return video if video.is_file() else None


def format_length(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def length_of(poster_path) -> float | None:
    """The clip's length in seconds, as its poster records it, or None."""
    try:
        reader = QImageReader(str(poster_path))
        value = reader.text(POSTER_KEY)
        return float(value) if value else None
    except (ValueError, TypeError):
        return None


def make_poster(frame: QImage, seconds: float) -> bytes:
    """The poster PNG: the clip's first frame with a play badge and its length."""
    image = frame.convertToFormat(QImage.Format.Format_RGB32)
    width, height = image.width(), image.height()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Sized to the frame, within limits, so a tiny clip is not all badge.
    radius = max(10.0, min(34.0, min(width, height) * 0.12))
    margin = radius * 0.5
    centre = QPointF(margin + radius, height - margin - radius)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 170))
    painter.drawEllipse(centre, radius, radius)
    painter.setBrush(QColor("#ffffff"))
    r = radius * 0.45
    painter.drawPolygon(QPolygonF([
        QPointF(centre.x() - r * 0.6, centre.y() - r),
        QPointF(centre.x() - r * 0.6, centre.y() + r),
        QPointF(centre.x() + r, centre.y()),
    ]))
    label = format_length(seconds)
    font = QFont()
    font.setPixelSize(max(10, int(radius * 0.7)))
    font.setBold(True)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    box = QRectF(centre.x() + radius + 6, centre.y() - metrics.height() / 2 - 3,
                 metrics.horizontalAdvance(label) + 14, metrics.height() + 6)
    painter.setBrush(QColor(0, 0, 0, 170))
    painter.drawRoundedRect(box, 4, 4)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    image.setText(POSTER_KEY, f"{seconds:.2f}")
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def copy_file(path) -> None:
    """Put a file on the clipboard, to paste into a chat or a folder."""
    import clipboard

    clipboard.copy_files([path])


def move_with(image_source: Path, image_target: Path) -> None:
    """A poster moved: its clip follows, under the matching name."""
    video = clip_for(image_source)
    if video is None:
        return
    import os

    try:
        os.replace(video, Path(image_target).with_suffix(SUFFIX))
    except OSError:
        pass


# -- GIF export ---------------------------------------------------------------------------------
class GifError(RuntimeError):
    pass


def frames_of(video: Path, fps: int = GIF_FPS, max_seconds: int = GIF_MAX_SECONDS,
              max_width: int = GIF_MAX_WIDTH, progress=None) -> list[tuple[QImage, int]]:
    """Pictures from the clip, `fps` a second, with how long each shows (ms).

    The clip is played muted at several times normal speed into a video sink;
    a frame is kept each time the clip's own clock passes the next sample.
    `progress(seconds_done)` is called as it goes; returning False stops early.
    """
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

    step = int(1_000_000 / fps)
    limit = int(max_seconds * 1_000_000)
    kept: list[tuple[int, QImage]] = []
    state = {"next": 0, "error": "", "stop": False}
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    loop = QEventLoop()

    def on_frame(frame) -> None:
        if not frame.isValid() or state["stop"]:
            return
        start = frame.startTime()
        if start < state["next"]:
            return
        if start > limit:
            state["stop"] = True
            player.stop()
            loop.quit()
            return
        image = frame.toImage()
        if image.isNull():
            return
        if image.width() > max_width:
            image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        kept.append((start, image))
        state["next"] = start + step
        if progress is not None and progress(start / 1_000_000) is False:
            state["stop"] = True
            player.stop()
            loop.quit()

    def on_status(status) -> None:
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            if status == QMediaPlayer.MediaStatus.InvalidMedia:
                state["error"] = "The clip could not be read."
            loop.quit()

    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(lambda _e, message: (state.update(error=message), loop.quit()))
    player.setSource(QUrl.fromLocalFile(str(video)))
    player.setPlaybackRate(8.0)
    player.play()
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(max(30_000, int(max_seconds * 1000)))
    loop.exec()
    player.stop()
    if state["error"] and not kept:
        raise GifError(state["error"])
    out = []
    for index, (start, image) in enumerate(kept):
        following = kept[index + 1][0] if index + 1 < len(kept) else start + step
        out.append((image, max(20, round((following - start) / 1000))))
    return out


def export_gif(video: Path, target: Path, progress=None, **options) -> int:
    """Write the clip as an animated GIF. Returns the number of frames written."""
    from PIL import Image

    frames = frames_of(Path(video), progress=progress, **options)
    if not frames:
        raise GifError("No pictures could be read from the clip.")
    pictures, durations = [], []
    for image, duration in frames:
        rgb = image.convertToFormat(QImage.Format.Format_RGB888)
        picture = Image.frombytes("RGB", (rgb.width(), rgb.height()), bytes(rgb.constBits()),
                                  "raw", "RGB", rgb.bytesPerLine())
        pictures.append(picture.quantize(colors=255, method=Image.Quantize.MEDIANCUT))
        durations.append(duration)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pictures[0].save(target, save_all=True, append_images=pictures[1:], duration=durations,
                     loop=0, optimize=True, disposal=1)
    return len(pictures)
