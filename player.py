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
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QShortcut
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
import skins
import storage

# Where the two places a clip plays read their choice from (config key
# clip_player): in ShadowSnip, or handed to the computer's video player.
PLAY_HERE = "app"
PLAY_EXTERNAL = "external"
PLAYER_CHOICES = ((PLAY_HERE, "In ShadowSnip"), (PLAY_EXTERNAL, "In your video player"))

PLAYER_STYLE = """
QWidget#ClipPlayer { background: transparent; }
QLabel#ClipTime { color: #b5b5c0; font-size: 12px; }
QPushButton#ClipPlay {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 4px 12px; min-width: 64px;
}
QPushButton#ClipPlay:hover { background: #34343d; }
QPushButton#ClipExternal {
    background: transparent; color: #b5b5c0; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 4px 10px;
}
QPushButton#ClipExternal:hover { background: #2a2a31; color: #e6e6ec; }
QSlider::groove:horizontal { height: 4px; background: #3a3a44; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #e81123; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #e6e6ec; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}
"""


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ClipPlayer")
        self.setStyleSheet(skins.style(PLAYER_STYLE))
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

        self.screen_area = _Screen()
        self.screen_area.clicked.connect(self.toggle)
        self.btn_play = QPushButton("Play")
        self.btn_play.setObjectName("ClipPlay")
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
        self.btn_external.setObjectName("ClipExternal")
        self.btn_external.setToolTip("Play the clip in this computer's video player, for fullscreen or frame by frame")
        self.btn_external.clicked.connect(self.open_external)
        for button in (self.btn_play, self.btn_external):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addWidget(self.btn_play)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time)
        controls.addWidget(self.btn_external)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.screen_area, 1)
        layout.addLayout(controls)

        play_key = QShortcut(QKeySequence("Space"), self, self.toggle)
        play_key.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

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

    def unload(self) -> None:
        """Stop and let go of the file, so it can be moved or removed."""
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
            player.setPosition(0)
            self._at_end = False
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
        player.setPosition(max(0, int(ms)))

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
        self._show_time(ms)

    def _on_duration(self, ms: int) -> None:
        if ms > 0:
            self._length_ms = int(ms)
            self.slider.setRange(0, self._length_ms)
            self._show_time(self.slider.value())

    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("Pause" if playing else "Play")

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

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
        self.time.setText(f"{clips.format_length(ms / 1000)} / {clips.format_length(self._length_ms / 1000)}")

    def restyle(self) -> None:
        self.setStyleSheet(skins.style(PLAYER_STYLE))
