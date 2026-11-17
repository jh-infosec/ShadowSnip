"""Trimming a video clip (0.14.2): keep the part between two times.

## How

No FFmpeg program is installed with ShadowSnip, only the FFmpeg libraries
inside Qt Multimedia, which can play a file and can encode frames but cannot
cut one. So a trim is a re-encode: the clip is played, muted, from the start
point into a `QVideoSink`, and every frame up to the end point is sent into a
new MP4 through the same `QVideoFrameInput` and `QMediaRecorder` set-up that
records clips, with its time moved back by the start. The cut is therefore
exact to the frame, not to the nearest key frame as a copy-only cut would be.

Playback runs at `TRIM_RATE` times normal speed. Frames wait in a short queue
for the encoder; when the queue is full, playback pauses until the encoder
catches up, so nothing is skipped and memory stays small even while the
encoder is still starting (Windows' H.264 can take a second or two).

Sound is not carried over: Qt has no way to cut it to match. A clip recorded
with the microphone loses its sound when trimmed, and the player says so
before you save.

## Keeping the original

The first trim moves the original aside as `<name>.untrimmed.mp4`; later trims
start from the current clip but leave that file alone, so **Undo trim**
always gets back the clip as it was recorded. It travels with the clip when
the clip is moved or removed (`clips.move_with`). The poster is remade from
the trimmed clip's first frame, with its new length.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QImage

import clips
import storage

UNTRIMMED = ".untrimmed"
# How much faster than normal the clip is played while it is re-encoded.
TRIM_RATE = 2.0
# Frames waiting for the encoder before playback pauses.
QUEUE_HIGH = 12
QUEUE_LOW = 4
# A trim keeps at least this much (ms): an encoder needs a frame or two.
MIN_KEEP_MS = 200
# No progress for this long (ms) and the trim is given up.
STALL_MS = 15_000


class TrimError(RuntimeError):
    pass


def untrimmed_of(video) -> Path:
    """Where the clip as recorded is kept once it has been trimmed."""
    video = Path(video)
    return video.with_name(video.stem + UNTRIMMED + clips.SUFFIX)


def is_trimmed(video) -> bool:
    return video is not None and untrimmed_of(video).is_file()


def is_untrimmed_copy(path) -> bool:
    """Whether a file is a kept original, not a clip in its own right."""
    return Path(path).name.endswith(UNTRIMMED + clips.SUFFIX)


def reencode(source: Path, target: Path, start_ms: int, end_ms: int, progress=None) -> tuple[QImage, float]:
    """Write `start_ms`..`end_ms` of `source` to `target` as a new MP4.

    Returns the first frame and the new length in seconds. `progress(fraction)`
    is called as it goes; returning False cancels (TrimError).
    """
    from PySide6.QtMultimedia import (
        QMediaCaptureSession,
        QMediaMetaData,
        QMediaPlayer,
        QMediaRecorder,
        QVideoFrame,
        QVideoFrameInput,
        QVideoSink,
    )

    import recorder as rec_mod

    start_us, end_us = int(start_ms) * 1000, int(end_ms) * 1000
    if end_us - start_us < MIN_KEEP_MS * 1000:
        raise TrimError("Keep at least a fraction of a second.")
    target = Path(target)
    if target.exists():
        target.unlink()

    loop = QEventLoop()
    state = {"error": "", "first": None, "last_us": -1, "sent": 0, "decoded_all": False,
             "stopping": False, "done": False, "size": None, "fps": rec_mod.DEFAULT_FPS,
             "paused": False}
    queue: deque = deque()
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    session = QMediaCaptureSession()
    frame_input = QVideoFrameInput()
    session.setVideoFrameInput(frame_input)
    encoder = QMediaRecorder()
    session.setRecorder(encoder)
    stall = QTimer()
    stall.setSingleShot(True)

    def fail(message: str) -> None:
        if not state["error"]:
            state["error"] = message
        loop.quit()

    def finish_encoding() -> None:
        if state["stopping"]:
            return
        state["stopping"] = True
        player.stop()
        if state["sent"] == 0:
            fail("No pictures could be read in that part of the clip.")
            return
        encoder.stop()

    def pump() -> None:
        while queue:
            image, at = queue[0]
            frame = QVideoFrame(image)
            frame.setStartTime(at)
            frame.setEndTime(at + int(1_000_000 / state["fps"]))
            if not frame_input.sendVideoFrame(frame):
                break
            queue.popleft()
            state["sent"] += 1
            stall.start(STALL_MS)
        if state["paused"] and len(queue) <= QUEUE_LOW and not state["decoded_all"]:
            state["paused"] = False
            player.play()
        if not queue and state["decoded_all"]:
            finish_encoding()

    def begin_encoder(size) -> None:
        encoder.setMediaFormat(rec_mod._codec_and_format())
        encoder.setQuality(QMediaRecorder.Quality.HighQuality)
        encoder.setVideoFrameRate(state["fps"])
        encoder.setVideoResolution(size)
        encoder.setOutputLocation(QUrl.fromLocalFile(str(target)))
        encoder.record()

    def on_frame(frame) -> None:
        if state["stopping"] or state["decoded_all"] or not frame.isValid():
            return
        at = frame.startTime()
        if at < start_us - 1000 or at <= state["last_us"]:
            return
        if at >= end_us:
            state["decoded_all"] = True
            player.pause()
            pump()
            return
        image = frame.toImage()
        if image.isNull():
            return
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        width, height = rec_mod.even_size(image.width(), image.height())
        if state["size"] is None:
            from PySide6.QtCore import QSize

            state["size"] = QSize(width, height)
            state["first"] = image.copy(0, 0, width, height)
            begin_encoder(state["size"])
        state["last_us"] = at
        queue.append((image.copy(0, 0, state["size"].width(), state["size"].height()), max(0, at - start_us)))
        stall.start(STALL_MS)
        if progress is not None and progress(min(1.0, (at - start_us) / max(1, end_us - start_us))) is False:
            fail("Trim cancelled.")
            return
        if len(queue) >= QUEUE_HIGH and not state["paused"]:
            state["paused"] = True
            player.pause()
        pump()

    def on_status(status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            rate = player.metaData().value(QMediaMetaData.Key.VideoFrameRate)
            try:
                if rate and float(rate) > 0:
                    state["fps"] = max(1, min(60, round(float(rate))))
            except (TypeError, ValueError):
                pass
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            state["decoded_all"] = True
            pump()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            fail("The clip could not be read.")

    def on_encoder_state(rec_state) -> None:
        if rec_state == QMediaRecorder.RecorderState.StoppedState and state["stopping"]:
            state["done"] = True
            loop.quit()

    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(lambda _e, message: fail(message or "The clip could not be read."))
    frame_input.readyToSendVideoFrame.connect(pump)
    encoder.recorderStateChanged.connect(on_encoder_state)
    encoder.errorOccurred.connect(lambda _e, message: fail(message or "The trimmed clip could not be written."))
    stall.timeout.connect(lambda: fail("Trimming stopped making progress."))

    player.setSource(QUrl.fromLocalFile(str(source)))
    player.setPlaybackRate(TRIM_RATE)
    if start_us > 0:
        player.setPosition(int(start_ms))
    player.play()
    stall.start(STALL_MS)
    loop.exec()
    stall.stop()
    player.stop()
    player.setSource(QUrl())
    if state["error"] or not state["done"]:
        if encoder.recorderState() != QMediaRecorder.RecorderState.StoppedState:
            encoder.stop()
        _discard(target)
        raise TrimError(state["error"] or "The trimmed clip could not be written.")
    written = Path(encoder.actualLocation().toLocalFile() or target)
    if written != target and written.is_file():
        os.replace(written, target)
    if not target.is_file() or target.stat().st_size == 0:
        _discard(target)
        raise TrimError("The trimmed clip could not be written.")
    seconds = (state["last_us"] - start_us) / 1_000_000 + 1 / state["fps"]
    return state["first"], seconds


def _discard(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _write_poster(poster: Path, frame: QImage, seconds: float) -> None:
    storage.write_atomic(poster, clips.make_poster(frame, seconds))


def trim(video, start_ms: int, end_ms: int, progress=None) -> float:
    """Trim the clip in place, keeping the clip as recorded aside. Returns the new length."""
    video = Path(video)
    if not video.is_file():
        raise TrimError("This clip's file is no longer there.")
    working = video.with_name(video.stem + ".trimming" + clips.SUFFIX)
    frame, seconds = reencode(video, working, start_ms, end_ms, progress)
    kept = untrimmed_of(video)
    try:
        if kept.is_file():
            storage.replace_with_retry(working, video)
        else:
            storage.replace_with_retry(video, kept)
            storage.replace_with_retry(working, video)
    except OSError as exc:
        _discard(working)
        raise TrimError(f"Could not replace the clip: {exc}") from exc
    _write_poster(video.with_suffix(".png"), frame, seconds)
    return seconds


def untrim(video) -> float:
    """Put the clip back as it was recorded. Returns its length."""
    video = Path(video)
    kept = untrimmed_of(video)
    if not kept.is_file():
        raise TrimError("This clip has not been trimmed.")
    frames = clips.frames_of(kept, fps=1, max_seconds=1, max_width=1_000_000)
    try:
        storage.replace_with_retry(kept, video)
    except OSError as exc:
        raise TrimError(f"Could not put the clip back: {exc}") from exc
    seconds = _length(video)
    if frames:
        _write_poster(video.with_suffix(".png"), frames[0][0], seconds)
    return seconds


def _length(video: Path) -> float:
    """The clip's length in seconds, as its file says."""
    from PySide6.QtMultimedia import QMediaPlayer

    player = QMediaPlayer()
    loop = QEventLoop()
    found = {"ms": 0}

    def on_duration(ms):
        if ms > 0:
            found["ms"] = ms
            loop.quit()

    player.durationChanged.connect(on_duration)
    player.mediaStatusChanged.connect(
        lambda status: loop.quit() if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                                 QMediaPlayer.MediaStatus.InvalidMedia) else None)
    QTimer.singleShot(5000, loop.quit)
    player.setSource(QUrl.fromLocalFile(str(video)))
    if not found["ms"]:
        loop.exec()
    found["ms"] = found["ms"] or player.duration()
    player.setSource(QUrl())
    return found["ms"] / 1000
