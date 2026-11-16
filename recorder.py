"""Recording a video clip of part of the screen (0.14.0).

Qt Multimedia does the encoding, through the FFmpeg it ships with PySide6, so
nothing extra is installed. ShadowSnip feeds it frames itself
(`QVideoFrameInput`): a timer grabs the chosen area of the screen several
times a second and hands each picture over with its time. That is what makes
a clip of exactly the area picked, the same way on Windows and on X11, where
Qt's own screen capture only records whole screens.

## Pictures

- Only the area is grabbed, not the whole screen, each frame: at 4K that is
  the difference between copying a few hundred thousand pixels and 8 million.
- The area is one screen's: a selection across two screens records the part on
  the screen holding most of it. Encoders want one fixed frame size and one
  scale, and two monitors at different scales would give neither.
- Frame width and height are made even: H.264 and MPEG-4 work in 2x2 blocks
  and refuse odd sizes.
- Each frame is stamped with the time it was grabbed (paused time left out),
  so a slow grab makes a frame last longer instead of making the clip run
  fast, and a microphone stays in step.

## Encoding

MP4, with H.264 where the platform's FFmpeg build offers it (Windows usually
does, through Media Foundation) and MPEG-4 Part 2 where it does not (Linux
builds of PySide6 leave H.264 out). Both play in VLC, Windows' Media Player and
most chat apps.

## Sound

None unless asked for: `microphone=True` adds the default microphone. There
is no "record the computer's sound" option; Qt cannot capture system audio
portably, and evidence clips rarely want it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QImage

# Frames per second offered in Settings.
FRAME_RATES = (10, 15, 30)
DEFAULT_FPS = 15
# A clip stops by itself after this long (Settings can change it), so a
# forgotten recording does not fill the disk.
DEFAULT_MAX_SECONDS = 10 * 60
MAX_MINUTES_RANGE = (1, 60)


class RecorderError(RuntimeError):
    pass


def even_size(width: int, height: int) -> tuple[int, int]:
    """The largest even width and height that fit: encoders need both even."""
    return max(2, width - width % 2), max(2, height - height % 2)


def screen_for(rect: QRect):
    """The screen holding most of `rect`, and the part of `rect` on it."""
    best, best_area, best_part = None, -1, QRect()
    for screen in QGuiApplication.screens():
        part = screen.geometry().intersected(rect)
        area = part.width() * part.height() if not part.isEmpty() else 0
        if area > best_area:
            best, best_area, best_part = screen, area, part
    if best is None or best_area <= 0:
        raise RecorderError("The area to record is not on any screen.")
    return best, best_part


def grab_area(screen, rect: QRect) -> QImage:
    """`rect` (global logical) from `screen`, as a picture in physical pixels."""
    origin = screen.geometry().topLeft()
    pixmap = screen.grabWindow(0, rect.x() - origin.x(), rect.y() - origin.y(), rect.width(), rect.height())
    return pixmap.toImage()


def _codec_and_format():
    from PySide6.QtMultimedia import QMediaFormat

    media = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
    codecs = media.supportedVideoCodecs(QMediaFormat.ConversionMode.Encode)
    for codec in (QMediaFormat.VideoCodec.H264, QMediaFormat.VideoCodec.MPEG4):
        if codec in codecs:
            media.setVideoCodec(codec)
            return media
    raise RecorderError("This computer's video encoder cannot write MP4 (no H.264 or MPEG-4 codec).")


class Recorder(QObject):
    """Records an area of the screen to an MP4 file.

    Signals: `tick(seconds)` once a second while recording, `finished(path)`
    when the file is complete, `failed(message)` if it could not be made.
    """

    tick = Signal(int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, rect: QRect, path: Path, fps: int = DEFAULT_FPS, microphone: bool = False,
                 max_seconds: int = DEFAULT_MAX_SECONDS, grab=grab_area, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.fps = fps if fps in FRAME_RATES else DEFAULT_FPS
        self.microphone = bool(microphone)
        self.max_seconds = max(1, int(max_seconds))
        self.screen, self.rect = screen_for(rect)
        self._grab = grab
        self.first_frame: QImage | None = None
        self.frames_sent = 0
        self.frames_dropped = 0
        self.paused = False
        self._active = 0.0          # seconds recorded before the current run
        self._run_started = None    # monotonic time the current run began
        self._last_tick = -1
        self._stopping = False
        self._size: QSize | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, round(1000 / self.fps)))
        self._timer.timeout.connect(self._frame)

    # -- control -----------------------------------------------------------
    def start(self) -> None:
        from PySide6.QtMultimedia import (
            QAudioInput,
            QMediaCaptureSession,
            QMediaRecorder,
            QVideoFrameFormat,
            QVideoFrameInput,
        )

        first = self._grab(self.screen, self.rect)
        if first.isNull():
            raise RecorderError("The screen could not be read.")
        width, height = even_size(first.width(), first.height())
        self._size = QSize(width, height)
        self.first_frame = first.copy(0, 0, width, height)

        self._session = QMediaCaptureSession(self)
        self._input = QVideoFrameInput(
            QVideoFrameFormat(self._size, QVideoFrameFormat.PixelFormat.Format_BGRA8888), self)
        self._session.setVideoFrameInput(self._input)
        if self.microphone:
            self._audio = QAudioInput(self)
            self._session.setAudioInput(self._audio)
        self._recorder = QMediaRecorder(self)
        self._session.setRecorder(self._recorder)
        self._recorder.setMediaFormat(_codec_and_format())
        self._recorder.setQuality(QMediaRecorder.Quality.HighQuality)
        self._recorder.setVideoFrameRate(self.fps)
        self._recorder.setVideoResolution(self._size)
        self._recorder.setOutputLocation(QUrl.fromLocalFile(str(self.path)))
        self._recorder.errorOccurred.connect(self._on_error)
        self._recorder.recorderStateChanged.connect(self._on_state)
        self._recorder.record()
        self._run_started = time.monotonic()
        self._send(self.first_frame)
        self._timer.start()

    def pause(self) -> None:
        if self.paused or self._stopping:
            return
        self.paused = True
        self._timer.stop()
        self._active = self.elapsed()
        self._run_started = None
        self._recorder.pause()

    def resume(self) -> None:
        if not self.paused or self._stopping:
            return
        self.paused = False
        self._run_started = time.monotonic()
        self._recorder.record()
        self._timer.start()

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._timer.stop()
        self._active = self.elapsed()
        self._run_started = None
        self._recorder.stop()

    def elapsed(self) -> float:
        """Seconds recorded so far, pauses left out."""
        if self._run_started is None:
            return self._active
        return self._active + (time.monotonic() - self._run_started)

    @property
    def recording(self) -> bool:
        return not self._stopping

    # -- frames ------------------------------------------------------------
    def _frame(self) -> None:
        seconds = self.elapsed()
        if int(seconds) != self._last_tick:
            self._last_tick = int(seconds)
            self.tick.emit(self._last_tick)
        if seconds >= self.max_seconds:
            self.stop()
            return
        image = self._grab(self.screen, self.rect)
        if image.isNull():
            self.frames_dropped += 1
            return
        if image.width() < self._size.width() or image.height() < self._size.height():
            self.frames_dropped += 1  # the screen changed resolution mid-clip
            return
        self._send(image.copy(0, 0, self._size.width(), self._size.height()))

    def _send(self, image: QImage) -> None:
        from PySide6.QtMultimedia import QVideoFrame

        frame = QVideoFrame(image.convertToFormat(QImage.Format.Format_ARGB32))
        start = int(self.elapsed() * 1_000_000)
        frame.setStartTime(start)
        frame.setEndTime(start + int(1_000_000 / self.fps))
        if self._input.sendVideoFrame(frame):
            self.frames_sent += 1
        else:
            self.frames_dropped += 1  # the encoder is behind: skip, keep time

    # -- results -----------------------------------------------------------
    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaRecorder

        if state != QMediaRecorder.RecorderState.StoppedState or not self._stopping:
            return
        written = Path(self._recorder.actualLocation().toLocalFile() or self.path)
        if written.is_file() and written.stat().st_size > 0:
            self.path = written
            self.finished.emit(str(written))
        else:
            self.failed.emit("The clip could not be written.")

    def _on_error(self, _error, message: str) -> None:
        self._timer.stop()
        self._stopping = True
        self.failed.emit(message or "Recording failed.")
