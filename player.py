"""Playing a video clip inside ShadowSnip (0.14.1).

A clip shows where a snip would: in the main window straight after it is
recorded, and in the full-size view from the snip list. Before 0.14.1 a clip
only ever opened in the computer's video player, and the main window went on
showing the snip taken before it.

## Why frames are painted, not shown in a QVideoWidget

Qt's `QVideoWidget` puts a native window inside ours. That window ignores the
skins' rounded, painted backgrounds, sits on top of anything drawn over it,
and on some Windows graphics drivers stays black until the window is resized.
A clip here is short, small and at most 30 frames a second, so the player
asks Qt for each frame as a picture (`QVideoSink`) and paints it, scaled to
fit, the same way the snip canvas paints a snip. That looks the same in every
skin and on every platform, and works offscreen in the tests.

## Controls

Play / Pause (Space, or a click on the picture), a position slider to drag,
the time, and "Open in video player" for fullscreen or frame stepping, which
the computer's own player does better. Before playing, the poster (the first
frame, with its play badge) is shown, so a clip on screen looks like the clip
in the list.

Sound plays when the clip has any (a clip recorded with the microphone on).
The sound system is only opened for such a clip, see `_on_has_audio`.

The buttons carry no style of their own: they take the window's, so they
look like every other button in the current skin. The window decides the
side margins of the controls (`set_control_margins`), so they line up with
its other rows.

## Trimming (0.14.2)

**Trim** swaps the slider for a trim bar with a handle at each end: drag
them, or play to the right spot and press **Start here** (I) or **End here**
(O). Play then plays only the part being kept. **Save trim** re-encodes that
part (`cliptrim`), keeps the clip as recorded aside, and remakes the poster;
**Undo trim** puts the recorded clip back. The window is told before the
file changes (`about_to_change`, so any other player lets go of it; Windows
will not replace an open file) and after (`changed`, so lists and lab.md
show the new length).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import clips
import cliptrim
import skins
import storage

# Where the two places a clip plays read their choice from (config key
# clip_player): in ShadowSnip, or handed to the computer's video player.
PLAY_HERE = "app"
PLAY_EXTERNAL = "external"
PLAYER_CHOICES = ((PLAY_HERE, "In ShadowSnip"), (PLAY_EXTERNAL, "In your video player"))

# Buttons are left to the window's stylesheet, so they match the rest of it.
PLAYER_STYLE = """
QWidget#ClipPlayer { background: transparent; }
QLabel#ClipTime { color: #b5b5c0; font-size: 12px; }
QLabel#TrimInfo { color: #b5b5c0; font-size: 12px; }
QLabel#TrimNote { color: #f0a020; font-size: 12px; }
QSlider::groove:horizontal { height: 4px; background: #3a3a44; border-radius: 2px; }
QSlider::sub-page:horizontal { background: ACCENT; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #e6e6ec; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}
"""


def _style() -> str:
    return skins.style(PLAYER_STYLE).replace("ACCENT", skins.accent())


def format_ms(ms: int) -> str:
    """A time to the tenth of a second: 0:03.4."""
    ms = max(0, int(ms))
    whole = clips.format_length(ms // 1000)
    return f"{whole}.{(ms % 1000) // 100}"


class TrimBar(QWidget):
    """The clip's length as a bar, with the part kept between two handles, and the play position.

    Drag a handle to move that end; click or drag anywhere else to move the
    play position. Times are in milliseconds.
    """

    range_changed = Signal(int, int)
    seek_requested = Signal(int)

    HANDLE_W = 8
    GRAB = 10   # how close (px) a press must be to take a handle

    def __init__(self, parent=None):
        super().__init__(parent)
        self.length = 0
        self.start = 0
        self.end = 0
        self.position = 0
        self._held = None   # "start", "end", "position" or None
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_length(self, ms: int) -> None:
        self.length = max(0, int(ms))
        self.start, self.end = 0, self.length
        self.position = 0
        self.update()

    def set_range(self, start: int, end: int) -> None:
        start = max(0, min(int(start), self.length))
        end = max(0, min(int(end), self.length))
        gap = min(cliptrim.MIN_KEEP_MS, self.length)
        if end - start < gap:
            # Keep the two ends apart: whichever moved last pushes the other.
            if start != self.start:
                start = max(0, end - gap)
            else:
                end = min(self.length, start + gap)
        if (start, end) != (self.start, self.end):
            self.start, self.end = start, end
            self.update()
            self.range_changed.emit(start, end)

    def set_position(self, ms: int) -> None:
        self.position = max(0, min(int(ms), self.length))
        self.update()

    # geometry
    def _track(self) -> QRectF:
        pad = self.HANDLE_W
        return QRectF(pad, self.height() / 2 - 3, max(1, self.width() - 2 * pad), 6)

    def x_of(self, ms: int) -> float:
        track = self._track()
        return track.left() + (track.width() * ms / self.length if self.length else 0)

    def ms_at(self, x: float) -> int:
        track = self._track()
        if not self.length:
            return 0
        fraction = (x - track.left()) / track.width()
        return int(round(max(0.0, min(1.0, fraction)) * self.length))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track()
        accent = QColor(skins.accent())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a3a44"))
        painter.drawRoundedRect(track, 3, 3)
        if self.length:
            kept = QRectF(QPointF(self.x_of(self.start), track.top()), QPointF(self.x_of(self.end), track.bottom()))
            painter.setBrush(accent)
            painter.drawRect(kept)
            for ms in (self.start, self.end):
                x = self.x_of(ms)
                handle = QRectF(x - self.HANDLE_W / 2, 2, self.HANDLE_W, self.height() - 4)
                painter.setBrush(QColor("#e6e6ec"))
                painter.drawRoundedRect(handle, 2, 2)
            x = self.x_of(self.position)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(QPointF(x, 4), QPointF(x, self.height() - 4))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.length:
            return
        x = event.position().x()
        near = [(abs(x - self.x_of(ms)), name) for name, ms in (("start", self.start), ("end", self.end))]
        distance, name = min(near)
        self._held = name if distance <= self.GRAB else "position"
        self._drag_to(x)

    def mouseMoveEvent(self, event):
        if self._held is not None:
            self._drag_to(event.position().x())

    def mouseReleaseEvent(self, event):
        self._held = None

    def _drag_to(self, x: float) -> None:
        ms = self.ms_at(x)
        if self._held == "start":
            self.set_range(min(ms, self.end), self.end)
            self.set_position(self.start)
            self.seek_requested.emit(self.start)
        elif self._held == "end":
            self.set_range(self.start, max(ms, self.start))
            self.set_position(self.end)
            self.seek_requested.emit(self.end)
        else:
            self.set_position(ms)
            self.seek_requested.emit(ms)


def fit_rect(picture: QSize, box: QSize) -> QRectF:
    """Where a picture of `picture` size goes in `box`: as large as fits, centred, never enlarged past 2x."""
    if picture.isEmpty() or box.isEmpty():
        return QRectF()
    scale = min(box.width() / picture.width(), box.height() / picture.height(), 2.0)
    width, height = picture.width() * scale, picture.height() * scale
    return QRectF((box.width() - width) / 2, (box.height() - height) / 2, width, height)


class _Screen(QWidget):
    """The picture: the poster until playing, then each frame as it arrives."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.picture: QImage | None = None
        self.message = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def show_picture(self, image: QImage | None) -> None:
        self.picture = image if image is not None and not image.isNull() else None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0c0c0f"))
        if self.picture is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(fit_rect(self.picture.size(), self.size()), self.picture)
        elif self.message:
            painter.setPen(QColor("#9a9aa6"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parentWidget().setFocus()
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ClipPlayer(QWidget):
    """A clip with Play / Pause, a position slider, the time, and Open in video player."""

    # Something to say in the window's status line.
    notice = Signal(str)
    # The clip's file is about to be replaced (trim, undo trim): let go of it.
    about_to_change = Signal(str)
    # It was: lists, lab.md and any other view of it should catch up.
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ClipPlayer")
        self.setStyleSheet(_style())
        # Takes focus, so Space plays and pauses once the clip is clicked.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video: Path | None = None
        self.poster: QImage | None = None
        self._player = None   # made on first use: Qt Multimedia loads FFmpeg
        self._sink = None
        self._audio = None
        self._length_ms = 0
        self._dragging = False
        self._at_end = False
        self.trimming = False   # the trim bar is up
        self._pending_seek = None
        self._busy = False      # a trim is being written

        self.screen_area = _Screen()
        self.screen_area.clicked.connect(self.toggle)
        self.btn_play = QPushButton("Play")
        self.btn_play.setMinimumWidth(72)
        self.btn_play.setToolTip("Play or pause the clip (Space)")
        self.btn_play.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("ClipTime")
        self.btn_external = QPushButton("Open in video player")
        self.btn_external.setToolTip("Play the clip in this computer's video player, for fullscreen or frame by frame")
        self.btn_external.clicked.connect(self.open_external)
        self.btn_trim = QPushButton("Trim")
        self.btn_trim.setToolTip("Cut the start or end off the clip")
        self.btn_trim.clicked.connect(self.begin_trim)
        self.btn_untrim = QPushButton("Undo trim")
        self.btn_untrim.setToolTip("Put the clip back as it was recorded")
        self.btn_untrim.clicked.connect(self.undo_trim)
        self.btn_untrim.hide()

        # The trim row, under the controls while trimming.
        self.trim_bar = TrimBar()
        self.trim_bar.hide()
        self.trim_bar.range_changed.connect(self._on_trim_range)
        self.trim_bar.seek_requested.connect(self.seek)
        self.trim_info = QLabel("")
        self.trim_info.setObjectName("TrimInfo")
        self.trim_info.setMinimumWidth(self.trim_info.fontMetrics().horizontalAdvance("Keep 0:00:00.0 to 0:00:00.0  (000.0 s)") + 8)
        self.trim_note = QLabel("The trimmed clip will have no sound")
        self.trim_note.setObjectName("TrimNote")
        self.trim_note.hide()
        self.btn_mark_start = QPushButton("Start here")
        self.btn_mark_start.setToolTip("Keep from the current position (I)")
        self.btn_mark_start.clicked.connect(self.mark_start)
        self.btn_mark_end = QPushButton("End here")
        self.btn_mark_end.setToolTip("Keep up to the current position (O)")
        self.btn_mark_end.clicked.connect(self.mark_end)
        self.btn_trim_cancel = QPushButton("Cancel")
        self.btn_trim_cancel.clicked.connect(self.cancel_trim)
        self.btn_trim_save = QPushButton("Save trim")
        self.btn_trim_save.setObjectName("Primary")
        self.btn_trim_save.setToolTip("Keep only the marked part. The clip as recorded is kept, for Undo trim.")
        self.btn_trim_save.clicked.connect(self.save_trim)
        for button in (self.btn_play, self.btn_external, self.btn_trim, self.btn_untrim, self.btn_mark_start,
                       self.btn_mark_end, self.btn_trim_cancel, self.btn_trim_save):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        self.controls.addWidget(self.btn_play)
        self.controls.addWidget(self.slider, 1)
        self.controls.addWidget(self.trim_bar, 1)
        self.controls.addWidget(self.time)
        self.controls.addWidget(self.btn_untrim)
        self.controls.addWidget(self.btn_trim)
        self.controls.addWidget(self.btn_external)

        self.trim_row_widget = QWidget()
        self.trim_row = QHBoxLayout(self.trim_row_widget)
        self.trim_row.setSpacing(8)
        self.trim_row.addWidget(self.btn_mark_start)
        self.trim_row.addWidget(self.btn_mark_end)
        self.trim_row.addSpacing(6)
        self.trim_row.addWidget(self.trim_info)
        self.trim_row.addWidget(self.trim_note)
        self.trim_row.addStretch(1)
        self.trim_row.addWidget(self.btn_trim_cancel)
        self.trim_row.addWidget(self.btn_trim_save)
        self.trim_row_widget.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.screen_area, 1)
        layout.addLayout(self.controls)
        layout.addWidget(self.trim_row_widget)
        self.set_control_margins(0, 8, 0, 0)

        for key, action in (("Space", self.toggle), ("I", self.mark_start), ("O", self.mark_end)):
            shortcut = QShortcut(QKeySequence(key), self, action)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def set_control_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        """Space around the controls, to line them up with the window's other rows."""
        self.controls.setContentsMargins(left, top, right, bottom)
        self.trim_row.setContentsMargins(left, 6, right, bottom)

    # -- what is loaded ---------------------------------------------------------------
    def load(self, video: Path, poster: QImage | None = None) -> None:
        """Show this clip, stopped at its start, with its poster until it plays."""
        self.stop()
        self.video = Path(video)
        self.poster = poster if poster is not None and not poster.isNull() else None
        seconds = clips.length_of(self.video.with_suffix(".png"))
        self._length_ms = int((seconds or 0) * 1000)
        self.slider.setRange(0, self._length_ms)
        self.slider.setValue(0)
        self._at_end = False
        self.screen_area.message = "" if self.poster is not None else "Press Play"
        self.screen_area.show_picture(self.poster)
        self._show_time(0)
        self.btn_play.setText("Play")
        self._show_trim_controls(False)
        self.btn_untrim.setVisible(cliptrim.is_trimmed(self.video))

    def unload(self) -> None:
        """Stop and let go of the file, so it can be moved or removed."""
        self._show_trim_controls(False)
        self.stop()
        if self._player is not None:
            self._player.setSource(QUrl())
        self.video = None
        self.poster = None
        self.screen_area.show_picture(None)

    def is_playing(self) -> bool:
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer

        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # -- playing --------------------------------------------------------------------
    def _ensure_player(self):
        if self._player is not None:
            return self._player
        from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        # Sound is connected only for a clip that has some (see _on_has_audio).
        self._player.hasAudioChanged.connect(self._on_has_audio)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        return self._player

    def play(self) -> None:
        if self.video is None:
            return
        if not self.video.is_file():
            self.screen_area.message = "This clip's file is no longer there"
            self.screen_area.show_picture(None)
            return
        player = self._ensure_player()
        wanted = QUrl.fromLocalFile(str(self.video))
        if player.source() != wanted:
            player.setSource(wanted)
        if self._at_end:
            player.setPosition(self.trim_bar.start if self.trimming else 0)
            self._at_end = False
        if self.trimming:
            # Play the part being kept: from its start if outside it.
            here = player.position()
            if here < self.trim_bar.start or here >= self.trim_bar.end - 30:
                player.setPosition(self.trim_bar.start)
        player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        self.btn_play.setText("Play")

    def toggle(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def seek(self, ms: int) -> None:
        if self.video is None:
            return
        player = self._ensure_player()
        wanted = QUrl.fromLocalFile(str(self.video))
        if player.source() != wanted:
            player.setSource(wanted)
        self._at_end = False
        from PySide6.QtMultimedia import QMediaPlayer

        ms = max(0, int(ms))
        if player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            # A stopped player shows nothing; paused, it shows the frame sought.
            player.pause()
        if player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.NoMedia):
            # Still opening the file: a seek now would be lost.
            self._pending_seek = ms
        player.setPosition(ms)
        self.trim_bar.set_position(ms)
        if not self._dragging:
            self.slider.setValue(ms)
        self._show_time(ms)

    def open_external(self) -> None:
        if self.video is None:
            return
        self.pause()
        try:
            storage.open_file(self.video)
        except OSError as exc:
            self.notice.emit(f"Could not open the clip: {exc}")

    # -- from the player ----------------------------------------------------------------
    def _on_has_audio(self, has_audio: bool) -> None:
        """A clip with sound (recorded with the microphone): play it through the speakers.

        Only then: most clips are silent, and opening the sound system costs
        time, and on a Linux machine with a broken PipeWire set-up can take
        the whole program down. A silent clip never touches it.
        """
        if not has_audio or self._audio is not None or self._player is None:
            return
        from PySide6.QtMultimedia import QAudioOutput

        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)

    def _on_frame(self, frame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self.screen_area.message = ""
            self.screen_area.show_picture(image)

    def _on_position(self, ms: int) -> None:
        if not self._dragging:
            self.slider.setValue(int(ms))
        self.trim_bar.set_position(ms)
        self._show_time(ms)
        if self.trimming and self.is_playing() and ms >= self.trim_bar.end:
            self.pause()
            self._at_end = True

    def _on_duration(self, ms: int) -> None:
        if ms > 0:
            self._length_ms = int(ms)
            self.slider.setRange(0, self._length_ms)
            if not self.trimming:
                self.trim_bar.set_length(self._length_ms)
            self._show_time(self.slider.value())

    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("Pause" if playing else "Play")

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._pending_seek is not None and status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                                         QMediaPlayer.MediaStatus.BufferedMedia):
            ms, self._pending_seek = self._pending_seek, None
            self._player.setPosition(ms)
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            # The next Play starts from the beginning again; the last frame stays up.
            self._at_end = True
            self.btn_play.setText("Play")
            self.slider.setValue(self._length_ms)
            self._show_time(self._length_ms)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.screen_area.message = "This clip could not be played"
            self.screen_area.show_picture(None)

    def _on_error(self, _error, message: str) -> None:
        self.notice.emit(f"The clip could not be played: {message}" if message else "The clip could not be played")

    # -- the slider ----------------------------------------------------------------------
    def _on_slider_pressed(self) -> None:
        self._dragging = True

    def _on_slider_moved(self, value: int) -> None:
        self._show_time(value)
        self.seek(value)

    def _on_slider_released(self) -> None:
        self._dragging = False
        self.seek(self.slider.value())

    def _show_time(self, ms: int) -> None:
        if self.trimming:
            # To the tenth while trimming, to see where an end will fall.
            self.time.setText(f"{format_ms(ms)} / {format_ms(self._length_ms)}")
            return
        self.time.setText(f"{clips.format_length(ms / 1000)} / {clips.format_length(self._length_ms / 1000)}")

    def restyle(self) -> None:
        self.setStyleSheet(_style())
        self.trim_bar.update()

    # -- trimming ------------------------------------------------------------------------
    def _show_trim_controls(self, on: bool) -> None:
        self.trimming = on
        self.slider.setVisible(not on)
        self.trim_bar.setVisible(on)
        self.trim_row_widget.setVisible(on)
        self.btn_trim.setVisible(not on)
        self.btn_untrim.setVisible(not on and cliptrim.is_trimmed(self.video))
        self._show_time(self.slider.value())

    def begin_trim(self) -> None:
        """Up comes the trim bar, keeping the whole clip to start with."""
        if self.video is None or self._busy:
            return
        if not self.video.is_file():
            self.notice.emit("This clip's file is no longer there")
            return
        self.pause()
        self.trim_bar.set_length(self._length_ms)
        self.trim_bar.set_position(self.slider.value())
        has_sound = self._player is not None and self._player.hasAudio()
        self.trim_note.setVisible(has_sound)
        self._show_trim_controls(True)
        self._on_trim_range(self.trim_bar.start, self.trim_bar.end)
        self.setFocus()

    def cancel_trim(self) -> None:
        if self._busy:
            return
        self._show_trim_controls(False)

    def mark_start(self) -> None:
        if self.trimming:
            self.trim_bar.set_range(self.trim_bar.position, max(self.trim_bar.end, self.trim_bar.position))

    def mark_end(self) -> None:
        if self.trimming:
            self.trim_bar.set_range(min(self.trim_bar.start, self.trim_bar.position), self.trim_bar.position)

    def _on_trim_range(self, start: int, end: int) -> None:
        kept = (end - start) / 1000
        self.trim_info.setText(f"Keep {format_ms(start)} to {format_ms(end)}  ({kept:.1f} s)")
        whole = start <= 0 and end >= self._length_ms
        self.btn_trim_save.setEnabled(not whole and not self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.btn_play, self.btn_trim_save, self.btn_trim_cancel, self.btn_mark_start,
                       self.btn_mark_end, self.btn_untrim, self.btn_trim, self.btn_external, self.trim_bar):
            widget.setEnabled(not busy)
        self.screen_area.setEnabled(not busy)

    def save_trim(self) -> None:
        """Keep only the marked part of the clip."""
        if self.video is None or self._busy or not self.trimming:
            return
        video, poster = self.video, self.video.with_suffix(".png")
        start, end = self.trim_bar.start, self.trim_bar.end
        self._release_for_change(video)
        self._set_busy(True)

        def progress(fraction: float) -> None:
            self.trim_info.setText(f"Trimming... {int(fraction * 100)}%")

        try:
            seconds = cliptrim.trim(video, start, end, progress=progress)
        except cliptrim.TrimError as exc:
            self._set_busy(False)
            self.load(video, QImage(str(poster)))
            self.notice.emit(f"Could not trim the clip: {exc}")
            return
        self._set_busy(False)
        self.load(video, QImage(str(poster)))
        self.notice.emit(f"Clip trimmed to {clips.format_length(seconds)}. Undo trim puts it back as recorded.")
        self.changed.emit(str(video))

    def undo_trim(self) -> None:
        """Put the clip back as it was recorded."""
        if self.video is None or self._busy or not cliptrim.is_trimmed(self.video):
            return
        video, poster = self.video, self.video.with_suffix(".png")
        self._release_for_change(video)
        self._set_busy(True)
        try:
            seconds = cliptrim.untrim(video)
        except cliptrim.TrimError as exc:
            self._set_busy(False)
            self.load(video, QImage(str(poster)))
            self.notice.emit(f"Could not undo the trim: {exc}")
            return
        self._set_busy(False)
        self.load(video, QImage(str(poster)))
        self.notice.emit(f"Clip put back as recorded ({clips.format_length(seconds)})")
        self.changed.emit(str(video))

    def _release_for_change(self, video: Path) -> None:
        """Let go of the file here and everywhere else showing it, before it is replaced."""
        self.stop()
        if self._player is not None:
            self._player.setSource(QUrl())
        self.about_to_change.emit(str(video))
