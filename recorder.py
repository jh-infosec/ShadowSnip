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

## Starting up

An encoder is not ready the moment recording is asked for. On Linux it takes
a few milliseconds; on Windows, where Qt tries the hardware H.264 encoders
before settling on one, it can take a second or more, and a frame offered
before then is refused. Offering frames on a timer regardless, and
counting the refusals as drops, would on Windows mean a clip with no
pictures in it at all. So the first frame is held and offered again until
the encoder takes it (Qt also says when it is ready), the clip's clock starts
at that moment, and a Stop pressed during the wait is carried out once the
first frame is in. An encoder that takes no frame within `WARMUP_SECONDS` is
reported as a failure, not saved as an empty file.

The frame input is created without a frame format. Given one, PySide6 6.11
never accepts a frame (found on Windows with 6.11.2, reproduced on Linux with
the same version; 6.12 is fine either way), so the encoder is left to read the
size and pixel format off the first frame.

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
# How long the encoder may take to accept its first frame before the clip is
# given up as failed. Windows' hardware encoders can take a few seconds.
WARMUP_SECONDS = 10.0


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


def _set_rate(target, fps: int) -> None:
    """Tell a frame or a frame format its rate, where this Qt has a way to."""
    for name in ("setStreamFrameRate", "setFrameRate"):
        setter = getattr(target, name, None)
        if setter is not None:
            try:
                setter(float(fps))
            except (TypeError, RuntimeError):
                continue
            return


class Recorder(QObject):
    """Records an area of the screen to an MP4 file.

    Signals: `tick(seconds)` once a second while recording, `finished(path)`
    when the file is complete, `failed(message)` if it could not be made.
    """

    tick = Signal(int)
    finished = Signal(str)
    failed = Signal(str)
    # The encoder took its first frame: the clip's clock runs from here.
    started = Signal()

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
        self._started = False        # the encoder has taken the first frame
        self._stop_wanted = False    # Stop pressed while it was still warming up
        self._failed = False
        self._warm_from = 0.0
        self._size: QSize | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, round(1000 / self.fps)))
        self._timer.timeout.connect(self._frame)

    # -- control -----------------------------------------------------------
    def start(self) -> None:
        try:
            from PySide6.QtMultimedia import (
                QAudioInput,
                QMediaCaptureSession,
                QMediaRecorder,
                QVideoFrameInput,
            )
        except ImportError as exc:  # e.g. libpulse0 missing on Linux (0.18.1)
            import clips

            raise RecorderError(clips.multimedia_problem(exc)) from exc

        first = self._grab(self.screen, self.rect)
        if first.isNull():
            raise RecorderError("The screen could not be read.")
        width, height = even_size(first.width(), first.height())
        self._size = QSize(width, height)
        self.first_frame = first.copy(0, 0, width, height)

        self._session = QMediaCaptureSession(self)
        # No frame format is given here, on purpose. PySide6 6.11 refuses every
        # frame of an input that was created with one (6.12 does not); without
        # it, the encoder takes its size and pixel format from the first frame,
        # which works on both.
        self._input = QVideoFrameInput(self)
        self._input.readyToSendVideoFrame.connect(self._offer_first)
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
        self._warm_from = time.monotonic()
        self._timer.start()
        self._offer_first()

    def _offer_first(self) -> None:
        """Offer the first frame until the encoder takes it; the clock starts then."""
        if self._started or self._stopping:
            return
        if self._send(self.first_frame, at=0.0):
            self._started = True
            self._run_started = time.monotonic()
            self.started.emit()
            if self._stop_wanted:
                self._stop_now()

    def pause(self) -> None:
        if self.paused or self._stopping or not self._started:
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
        if not self._started:
            # Still warming up: stop as soon as the first frame is in, so the
            # clip is never empty. _frame() gives up if that never happens.
            self._stop_wanted = True
            return
        self._stop_now()

    def _stop_now(self) -> None:
        self._stopping = True
        self._timer.stop()
        self._active = self.elapsed()
        self._run_started = None
        self._recorder.stop()

    def elapsed(self) -> float:
        """Seconds recorded so far, pauses and the encoder's start-up left out."""
        if self._run_started is None:
            return self._active
        return self._active + (time.monotonic() - self._run_started)

    @property
    def recording(self) -> bool:
        return not self._stopping

    @property
    def is_started(self) -> bool:
        """Whether the encoder has taken its first frame yet."""
        return self._started

    # -- frames ------------------------------------------------------------
    def _frame(self) -> None:
        if not self._started:
            self._offer_first()
            if not self._started and time.monotonic() - self._warm_from > WARMUP_SECONDS:
                self._fail("The video encoder did not start. Nothing was recorded.")
            return
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

    def _send(self, image: QImage, at: float | None = None) -> bool:
        from PySide6.QtMultimedia import QVideoFrame

        frame = QVideoFrame(image.convertToFormat(QImage.Format.Format_ARGB32))
        _set_rate(frame, self.fps)
        start = int((self.elapsed() if at is None else at) * 1_000_000)
        frame.setStartTime(start)
        frame.setEndTime(start + int(1_000_000 / self.fps))
        if self._input.sendVideoFrame(frame):
            self.frames_sent += 1
            return True
        if self._started:
            self.frames_dropped += 1  # the encoder is behind: skip, keep time
        return False

    def _fail(self, message: str) -> None:
        if self._failed:
            return
        self._failed = True
        self._stopping = True
        self._timer.stop()
        try:
            self._recorder.stop()
        except RuntimeError:
            pass
        self.failed.emit(message)

    # -- results -----------------------------------------------------------
    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaRecorder

        if state != QMediaRecorder.RecorderState.StoppedState or not self._stopping or self._failed:
            return
        written = Path(self._recorder.actualLocation().toLocalFile() or self.path)
        if written.is_file() and written.stat().st_size > 0:
            self.path = written
            self.finished.emit(str(written))
        else:
            self.failed.emit("The clip could not be written.")

    def _on_error(self, _error, message: str) -> None:
        self._fail(message or "Recording failed.")
