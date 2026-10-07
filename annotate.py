"""Marking up a snip: pen, highlighter, eraser, crop, redaction, undo.

The snip on screen in the preview window is drawn on directly. Every mark is
kept as an operation on top of the original capture, never baked into it, so

- undo is just dropping the last operation,
- the eraser hides whole marks (an operation of its own, so undo brings them
  back),
- and the image that gets saved is always rendered fresh from the original
  pixels, so ten rounds of edits cost nothing in quality.

Coordinates are stored in the original image's pixels, whatever the zoom on
screen, and pen widths are converted from screen pixels when a stroke starts,
so a line looks on the saved image the way it looked while drawing it.

## Redaction

Two modes. **Black out** replaces the pixels with solid black: nothing of the
original survives in the saved image. **Blur** shrinks the region to a few
pixels and scales it back up. It hides text well, but a blurred region can
still hint at what was there (line lengths, layout), so black out is the one
to use for passwords and hashes.

A redaction only protects the files ShadowSnip writes, which the application
rewrites after every edit. Copies made before the redaction (a paste into a
chat, Windows clipboard history) are outside its reach.

## Layout

    AnnotationDoc     the original image plus the list of operations
    AnnotCanvas       shows the doc and turns mouse drags into operations
    AnnotToolbar      the tool strip: pen, highlighter, eraser | crop, redact | undo
    OptionsPopup      width and colour for the pen and the highlighter
    RedactPopup       blur or black out
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

# -- palettes ---------------------------------------------------------------------
# The pen's colours come in six families, one per row, each running from light
# on the left to dark on the right: greys, reds, oranges and yellows, greens,
# blues, purples. A colour is found by its family, then by how strong it is.
PEN_COLUMNS = 5
PEN_COLORS = [
    "#ffffff", "#c8c8d0", "#8e8e9a", "#4a4a54", "#000000",  # greys
    "#ffb3c1", "#ff5c7a", "#e81123", "#a4001d", "#5c0011",  # reds
    "#fff59d", "#fff100", "#ffb900", "#ff8c00", "#b85c00",  # oranges, yellows
    "#b9f6ca", "#5ee07a", "#16c60c", "#0e8a3a", "#0a4d24",  # greens
    "#b3e5fc", "#4fc3f7", "#0091ff", "#0063b1", "#0a2f6b",  # blues
    "#e1bee7", "#c77dff", "#9b5cff", "#6a1b9a", "#3c0d5a",  # purples
]
# Highlighters: the bright few that read through text, in spectrum order.
HIGHLIGHTER_COLUMNS = 6
HIGHLIGHTER_COLORS = ["#fff100", "#ff7a1a", "#ff2fb4", "#9b5cff", "#2fd2ff", "#16e01c"]

PEN_WIDTHS = (1, 24)
HIGHLIGHTER_WIDTHS = (6, 48)
DEFAULT_PREFS = {
    "pen_color": "#e81123",
    "pen_width": 4,
    "highlighter_color": "#fff100",
    "highlighter_width": 18,
    "redact_mode": "black",
}
# How see-through the highlighter is. Strong enough to find on a dark
# terminal, light enough to read the text under it on a light page.
HIGHLIGHTER_ALPHA = 110
# Blur shrinks the region by this much in each direction before scaling it
# back up. Larger means less of the original survives.
BLUR_FACTOR = 14
# The eraser's reach around the pointer, in screen pixels.
ERASER_RADIUS = 9
# A drag shorter than this, in screen pixels, is a click: no crop, no box.
MIN_DRAG = 4

ACCENT = QColor("#2f8cff")


# -- operations ---------------------------------------------------------------------
@dataclass
class Stroke:
    id: int
    kind: str  # "pen" or "highlighter"
    color: str
    width: float  # in image pixels
    points: list = field(default_factory=list)  # QPointF, image pixels

    def path(self) -> QPainterPath:
        path = QPainterPath(self.points[0])
        if len(self.points) == 1:
            # A click with the pen is a dot.
            path.lineTo(self.points[0] + QPointF(0.01, 0.01))
        for point in self.points[1:]:
            path.lineTo(point)
        return path


@dataclass
class Redact:
    id: int
    rect: QRect  # image pixels
    mode: str  # "blur" or "black"


@dataclass
class Crop:
    id: int
    rect: QRect  # image pixels, in the original image


@dataclass
class Erase:
    id: int
    targets: frozenset  # ids of the marks hidden


class AnnotationDoc:
    """The original capture and the marks on it, in the order they were made."""

    def __init__(self, image: QImage):
        self.base = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.ops: list = []
        self._next = 1

    # -- editing ------------------------------------------------------------------
    def new_id(self) -> int:
        ident = self._next
        self._next += 1
        return ident

    def add(self, op) -> None:
        self.ops.append(op)

    def undo(self) -> bool:
        if not self.ops:
            return False
        self.ops.pop()
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self.ops)

    @property
    def edited(self) -> bool:
        return bool(self.ops)

    def erased(self) -> set:
        hidden: set = set()
        for op in self.ops:
            if isinstance(op, Erase):
                hidden |= set(op.targets)
        return hidden

    def crop_rect(self) -> QRect:
        """The part of the original that is kept: the last crop, or all of it."""
        for op in reversed(self.ops):
            if isinstance(op, Crop):
                return QRect(op.rect)
        return self.base.rect()

    # -- the eraser ---------------------------------------------------------------
    def hit(self, point: QPointF, radius: float, ignore=()) -> list[int]:
        """Ids of the visible marks within `radius` of `point` (image pixels)."""
        hidden = self.erased() | set(ignore)
        found = []
        for op in self.ops:
            if op.id in hidden:
                continue
            if isinstance(op, Stroke):
                reach = radius + op.width / 2
                if _near_polyline(point, op.points, reach):
                    found.append(op.id)
            elif isinstance(op, Redact):
                if QRectF(op.rect).adjusted(-radius, -radius, radius, radius).contains(point):
                    found.append(op.id)
        return found

    # -- rendering ------------------------------------------------------------------
    def render_full(self, hidden=()) -> QImage:
        """The original with every visible mark applied, before any crop."""
        image = self.base.copy()
        skip = self.erased() | set(hidden)
        painter = None
        for op in self.ops:
            if op.id in skip or isinstance(op, (Crop, Erase)):
                continue
            if isinstance(op, Stroke):
                if painter is None:
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                _paint_stroke(painter, op)
            elif isinstance(op, Redact):
                if painter is not None:
                    # A blur reads the pixels under it, strokes included, so
                    # everything drawn so far has to be on the image first.
                    painter.end()
                    painter = None
                _apply_redaction(image, op)
        if painter is not None:
            painter.end()
        return image

    def render(self, hidden=()) -> QImage:
        """What gets saved: the marks applied, then the crop."""
        full = self.render_full(hidden)
        rect = self.crop_rect().intersected(full.rect())
        return full.copy(rect).convertToFormat(QImage.Format.Format_RGB32)


def _paint_stroke(painter: QPainter, stroke: Stroke) -> None:
    color = QColor(stroke.color)
    if stroke.kind == "highlighter":
        color.setAlpha(HIGHLIGHTER_ALPHA)
        pen = QPen(color, stroke.width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.RoundJoin)
    else:
        pen = QPen(color, stroke.width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # One path rather than segment by segment, so a highlighter's overlapping
    # segments do not stack up into darker blotches.
    painter.drawPath(stroke.path())


def _apply_redaction(image: QImage, op: Redact) -> None:
    rect = op.rect.intersected(image.rect())
    if rect.isEmpty():
        return
    if op.mode == "blur":
        region = image.copy(rect)
        small = region.scaled(
            max(1, rect.width() // BLUR_FACTOR),
            max(1, rect.height() // BLUR_FACTOR),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        replacement = small.scaled(
            rect.width(), rect.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(rect.topLeft(), replacement)
        painter.end()
    else:
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(rect, QColor(0, 0, 0))
        painter.end()


def _near_polyline(point: QPointF, points, reach: float) -> bool:
    if not points:
        return False
    if len(points) == 1:
        return math.hypot(point.x() - points[0].x(), point.y() - points[0].y()) <= reach
    for a, b in zip(points, points[1:]):
        if _segment_distance(point, a, b) <= reach:
            return True
    return False


def _segment_distance(p: QPointF, a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / length))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


# -- the canvas -----------------------------------------------------------------------
class AnnotCanvas(QWidget):
    """The snip on screen, and the place it is marked up.

    With no tool selected it is just the picture, exactly as before. With a
    tool selected, a drag draws, highlights, erases, crops or redacts.
    """

    # Something about the image changed: a mark, an erase, a crop or an undo.
    edited = Signal()
    # Undo became available or ran out.
    undo_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(QSize(320, 200))
        self.setMouseTracking(True)
        self.doc: AnnotationDoc | None = None
        self.tool: str | None = None
        self.prefs = dict(DEFAULT_PREFS)
        self._message = ""
        self._rendered: QImage | None = None
        self._pixmap: QPixmap | None = None
        self._live: Stroke | None = None
        self._drag_from: QPointF | None = None
        self._drag_to: QPointF | None = None
        self._erasing: set[int] = set()
        self._pointer: QPointF | None = None

    # -- content ----------------------------------------------------------------
    def load(self, image: QImage | None) -> None:
        self.doc = AnnotationDoc(image) if image is not None else None
        self._message = ""
        self._cancel_gesture()
        self._refresh()
        self.undo_changed.emit(False)

    def set_message(self, text: str) -> None:
        """Text shown when there is no snip to show."""
        self._message = text
        if self.doc is None:
            self.update()

    def image(self) -> QImage | None:
        """The snip as it should be saved now."""
        return self.doc.render() if self.doc is not None else None

    def set_tool(self, tool: str | None) -> None:
        self._cancel_gesture()
        self.tool = tool
        self._sync_cursor()
        self.update()

    def _pointer_on_image(self) -> bool:
        return (
            self.tool is not None
            and self._pointer is not None
            and self._rendered is not None
            and self._target().contains(self._pointer)
        )

    def _sync_cursor(self) -> None:
        """Over the screenshot, the tool is drawn in place of the pointer.

        Everywhere else (the margins, the rest of the window) the ordinary
        arrow stays, so it is always clear where marks can go.
        """
        shape = Qt.CursorShape.BlankCursor if self._pointer_on_image() else Qt.CursorShape.ArrowCursor
        if self.cursor().shape() != shape:
            self.setCursor(shape)

    def undo(self) -> None:
        if self.doc is None or not self.doc.undo():
            return
        self._refresh()
        self.undo_changed.emit(self.doc.can_undo)
        self.edited.emit()

    # -- geometry -------------------------------------------------------------------
    def _target(self) -> QRectF:
        """Where the image is drawn: fitted, centred, never enlarged."""
        if self._rendered is None:
            return QRectF()
        w, h = self._rendered.width(), self._rendered.height()
        area = self.rect().adjusted(1, 1, -1, -1)
        scale = min(1.0, area.width() / max(1, w), area.height() / max(1, h))
        tw, th = w * scale, h * scale
        return QRectF(area.x() + (area.width() - tw) / 2,
                      area.y() + (area.height() - th) / 2, tw, th)

    def scale(self) -> float:
        target = self._target()
        if self._rendered is None or self._rendered.width() == 0:
            return 1.0
        return target.width() / self._rendered.width()

    def to_image(self, pos: QPointF) -> QPointF:
        """A point on the widget, in the original image's pixels."""
        target = self._target()
        s = self.scale() or 1.0
        crop = self.doc.crop_rect() if self.doc is not None else QRect()
        return QPointF((pos.x() - target.x()) / s + crop.x(),
                       (pos.y() - target.y()) / s + crop.y())

    def to_widget(self, point: QPointF) -> QPointF:
        target = self._target()
        s = self.scale()
        crop = self.doc.crop_rect() if self.doc is not None else QRect()
        return QPointF((point.x() - crop.x()) * s + target.x(),
                       (point.y() - crop.y()) * s + target.y())

    def _refresh(self) -> None:
        if self.doc is None:
            self._rendered = None
            self._pixmap = None
        else:
            self._rendered = self.doc.render(hidden=self._erasing)
            self._pixmap = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._pixmap = None

    # -- input --------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.doc is None or self.tool is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        point = self.to_image(pos)
        if self.tool in ("pen", "highlighter"):
            width_px = float(self.prefs[f"{self.tool}_width"])
            self._live = Stroke(
                id=self.doc.new_id(),
                kind=self.tool,
                color=self.prefs[f"{self.tool}_color"],
                width=max(0.5, width_px / (self.scale() or 1.0)),
                points=[point],
            )
        elif self.tool == "eraser":
            self._erasing = set()
            self._erase_at(pos)
        elif self.tool in ("crop", "redact"):
            self._drag_from = self._clamp(point)
            self._drag_to = self._drag_from
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._pointer = pos
        self._sync_cursor()
        if self._live is not None:
            self._live.points.append(self.to_image(pos))
        elif self.tool == "eraser" and event.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(pos)
        elif self._drag_from is not None:
            self._drag_to = self._clamp(self.to_image(pos))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.doc is None:
            return super().mouseReleaseEvent(event)
        changed = False
        if self._live is not None:
            self.doc.add(self._live)
            self._live = None
            changed = True
        elif self.tool == "eraser" and self._erasing:
            self.doc.add(Erase(self.doc.new_id(), frozenset(self._erasing)))
            self._erasing = set()
            changed = True
        elif self._drag_from is not None and self._drag_to is not None:
            rect = QRectF(self._drag_from, self._drag_to).normalized().toAlignedRect()
            rect = rect.intersected(self.doc.crop_rect())
            long_enough = min(rect.width(), rect.height()) * self.scale() >= MIN_DRAG
            if long_enough and self.tool == "crop":
                self.doc.add(Crop(self.doc.new_id(), rect))
                changed = True
            elif long_enough and self.tool == "redact":
                self.doc.add(Redact(self.doc.new_id(), rect, self.prefs["redact_mode"]))
                changed = True
            self._drag_from = self._drag_to = None
        if changed:
            self._refresh()
            self.undo_changed.emit(self.doc.can_undo)
            self.edited.emit()
        else:
            self.update()

    def leaveEvent(self, event):
        self._pointer = None
        self.update()
        super().leaveEvent(event)

    def _erase_at(self, pos: QPointF) -> None:
        radius = ERASER_RADIUS / (self.scale() or 1.0)
        hits = self.doc.hit(self.to_image(pos), radius, ignore=self._erasing)
        if hits:
            self._erasing |= set(hits)
            self._refresh()

    def _clamp(self, point: QPointF) -> QPointF:
        crop = QRectF(self.doc.crop_rect())
        return QPointF(min(max(point.x(), crop.left()), crop.right() + 1),
                       min(max(point.y(), crop.top()), crop.bottom() + 1))

    def _cancel_gesture(self) -> None:
        self._live = None
        self._drag_from = self._drag_to = None
        if self._erasing:
            self._erasing = set()
            if self.doc is not None:
                self._rendered = self.doc.render()

    # -- painting -----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101013"))
        painter.setPen(QPen(QColor("#2c2c33"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self._rendered is None:
            painter.setPen(QColor("#9a9aa6"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return

        target = self._target()
        if self._pixmap is None or self._pixmap.size() != target.size().toSize():
            pixmap = QPixmap.fromImage(self._rendered)
            if target.width() < self._rendered.width():
                pixmap = pixmap.scaled(
                    target.size().toSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._pixmap = pixmap
        painter.drawPixmap(target.topLeft(), self._pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(target)

        if self._live is not None:
            # The stroke in progress, drawn in screen space at the size it
            # will have on the image.
            live = Stroke(self._live.id, self._live.kind, self._live.color,
                          self._live.width * self.scale(),
                          [self.to_widget(p) for p in self._live.points])
            _paint_stroke(painter, live)

        if self._drag_from is not None and self._drag_to is not None:
            rect = QRectF(self.to_widget(self._drag_from), self.to_widget(self._drag_to)).normalized()
            if self.tool == "crop":
                shade = QColor(0, 0, 0, 140)
                outside = QPainterPath()
                outside.addRect(target)
                inner = QPainterPath()
                inner.addRect(rect)
                painter.fillPath(outside.subtracted(inner), shade)
                painter.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
            else:
                fill = QColor(0, 0, 0, 220) if self.prefs["redact_mode"] == "black" else QColor(47, 140, 255, 60)
                painter.fillRect(rect, fill)
                painter.setPen(QPen(ACCENT, 1))
            painter.drawRect(rect)

        if self._pointer_on_image():
            self._paint_tool_cursor(painter, target)

    def footprint(self) -> float:
        """How big the tool's mark is on screen, in pixels: what the cursor shows."""
        if self.tool in ("pen", "highlighter"):
            return float(self.prefs[f"{self.tool}_width"])
        if self.tool == "eraser":
            return ERASER_RADIUS * 2.0
        return 0.0

    def _paint_tool_cursor(self, painter: QPainter, target: QRectF) -> None:
        """The selected tool, at its real size, where the pointer is.

        The footprint is the exact size of the mark it will make (a pen dot as
        wide as the line, the highlighter's square tip, the eraser's reach),
        outlined dark and light so it shows on any screenshot. A small badge
        with the tool's icon sits beside it, so the tool in hand is never in
        doubt. Clipped to the screenshot: it is never drawn in the margins.
        """
        pos = self._pointer
        painter.save()
        painter.setClipRect(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = self.footprint()
        dark, light = QPen(QColor(0, 0, 0, 170), 2.4), QPen(QColor("#ffffff"), 1.0)

        if self.tool == "pen":
            r = max(1.5, size / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.prefs["pen_color"]))
            painter.drawEllipse(pos, r, r)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for pen in (dark, light):
                painter.setPen(pen)
                painter.drawEllipse(pos, r + 1.5, r + 1.5)
        elif self.tool == "highlighter":
            tip = QRectF(pos.x() - size / 2, pos.y() - size / 2, size, size)
            fill = QColor(self.prefs["highlighter_color"])
            fill.setAlpha(HIGHLIGHTER_ALPHA)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillRect(tip, fill)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for pen in (dark, light):
                painter.setPen(pen)
                painter.drawRect(tip.adjusted(-1, -1, 1, 1))
        elif self.tool == "eraser":
            painter.setBrush(QColor(255, 255, 255, 50))
            for pen in (dark, light):
                painter.setPen(pen)
                painter.drawEllipse(pos, ERASER_RADIUS, ERASER_RADIUS)
                painter.setBrush(Qt.BrushStyle.NoBrush)
        elif self.tool in ("crop", "redact") and self._drag_from is None:
            # Guides across the whole screenshot, for lining up the first corner.
            for pen in (QPen(QColor(0, 0, 0, 120), 1), QPen(QColor(255, 255, 255, 170), 1, Qt.PenStyle.DashLine)):
                painter.setPen(pen)
                painter.drawLine(QPointF(target.left(), pos.y()), QPointF(target.right(), pos.y()))
                painter.drawLine(QPointF(pos.x(), target.top()), QPointF(pos.x(), target.bottom()))

        # The badge: the tool's icon on a dark chip, down and to the right.
        reach = max(size / 2, 4) + 8
        chip = QRectF(pos.x() + reach, pos.y() + reach, 26, 26)
        painter.setPen(QPen(ACCENT, 1))
        painter.setBrush(QColor(26, 26, 31, 230))
        painter.drawRoundedRect(chip, 6, 6)
        color = self.prefs.get(f"{self.tool}_color") if self.tool in ("pen", "highlighter") else None
        icon_kind = self.tool
        icon = tool_icon(icon_kind, color, size=18).pixmap(18, 18)
        painter.drawPixmap(QPointF(chip.x() + 4, chip.y() + 4), icon)
        if self.tool == "redact":
            # Which redaction is armed: a black square or a blurred one.
            mark = QRectF(chip.right() - 9, chip.bottom() - 9, 7, 7)
            painter.setPen(QPen(QColor("#ffffff"), 0.8))
            painter.setBrush(QColor("#000000") if self.prefs["redact_mode"] == "black" else QColor(160, 170, 190))
            painter.drawRect(mark)
        painter.restore()


# -- icons ------------------------------------------------------------------------------
def tool_icon(kind: str, color: str | None = None, size: int = 22) -> QIcon:
    """Draw the tool strip's icons, so they ship without image files.

    The pen and highlighter carry a bar in their current colour under the
    glyph, so the colour in use is visible without opening anything.
    """
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ink = QColor("#e6e6ec")
    s = size
    pen = QPen(ink, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    if kind == "pen":
        body = QPainterPath()
        body.moveTo(s * 0.70, s * 0.12)
        body.lineTo(s * 0.86, s * 0.28)
        body.lineTo(s * 0.36, s * 0.78)
        body.lineTo(s * 0.16, s * 0.84)
        body.lineTo(s * 0.22, s * 0.64)
        body.closeSubpath()
        p.drawPath(body)
        p.drawLine(QPointF(s * 0.60, s * 0.22), QPointF(s * 0.76, s * 0.38))
    elif kind == "highlighter":
        body = QPainterPath()
        body.moveTo(s * 0.58, s * 0.10)
        body.lineTo(s * 0.86, s * 0.38)
        body.lineTo(s * 0.52, s * 0.72)
        body.lineTo(s * 0.24, s * 0.44)
        body.closeSubpath()
        p.drawPath(body)
        tip = QPainterPath()
        tip.moveTo(s * 0.30, s * 0.50)
        tip.lineTo(s * 0.46, s * 0.66)
        tip.lineTo(s * 0.30, s * 0.78)
        tip.lineTo(s * 0.18, s * 0.66)
        tip.closeSubpath()
        p.setBrush(QColor(color or "#fff100"))
        p.drawPath(tip)
    elif kind == "eraser":
        p.save()
        p.translate(s * 0.5, s * 0.48)
        p.rotate(-40)
        p.drawRoundedRect(QRectF(-s * 0.36, -s * 0.16, s * 0.72, s * 0.32), 3, 3)
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(-s * 0.36, -s * 0.16, s * 0.28, s * 0.32), 3, 3)
        p.restore()
        p.drawLine(QPointF(s * 0.30, s * 0.86), QPointF(s * 0.82, s * 0.86))
    elif kind == "crop":
        p.drawLine(QPointF(s * 0.28, s * 0.08), QPointF(s * 0.28, s * 0.72))
        p.drawLine(QPointF(s * 0.28, s * 0.72), QPointF(s * 0.92, s * 0.72))
        p.drawLine(QPointF(s * 0.08, s * 0.28), QPointF(s * 0.72, s * 0.28))
        p.drawLine(QPointF(s * 0.72, s * 0.28), QPointF(s * 0.72, s * 0.92))
    elif kind == "redact":
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.20, s * 0.76, s * 0.60), 2, 2)
        p.setBrush(ink)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(s * 0.22, s * 0.36, s * 0.40, s * 0.10))
        p.drawRect(QRectF(s * 0.22, s * 0.54, s * 0.56, s * 0.10))
    elif kind == "undo":
        # Drawn turning clockwise, then mirrored: the arrow turns back, the
        # way an undo arrow reads.
        p.translate(s, 0)
        p.scale(-1, 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(s * 0.22, s * 0.24, s * 0.56, s * 0.56), 30 * 16, 270 * 16)
        head = QPainterPath()
        head.moveTo(s * 0.70, s * 0.12)
        head.lineTo(s * 0.80, s * 0.36)
        head.lineTo(s * 0.56, s * 0.34)
        p.drawPath(head)

    if color and kind == "pen":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.90, s * 0.64, s * 0.10), 1.5, 1.5)
    p.end()
    return QIcon(pixmap)


# -- option popups -------------------------------------------------------------------
POPUP_STYLE = """
QFrame#Popup {
    background: #1f1f25; border: 1px solid #3a3a44; border-radius: 8px;
}
QLabel { color: #e6e6ec; }
QLabel#PopupTitle { font-weight: 600; }
QLabel#PopupValue { color: #9a9aa6; }
QLabel#PopupHint { color: #9a9aa6; font-size: 11px; }
QSlider::groove:horizontal { height: 4px; background: #3a3a44; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2f8cff; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #e6e6ec; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}
QPushButton#Mode {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 6px; padding: 8px 14px; text-align: left;
}
QPushButton#Mode:checked { border: 2px solid #2f8cff; background: #232a38; }
"""


class StrokePreview(QWidget):
    """A sample stroke at the chosen width and colour."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.color = "#ffffff"
        self.width_px = 4
        self.setFixedHeight(54)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#15151a"))
        if self.kind == "highlighter":
            # Some "text" to show it is see-through.
            p.setPen(QColor("#5c5c66"))
            for i, y in enumerate((18, 32)):
                p.drawText(12, y + 4, "nmap -sV -p- 10.10.10.3" if i == 0 else "445/tcp open microsoft-ds")
        w, h = self.width(), self.height()
        path = QPainterPath(QPointF(16, h * 0.62))
        path.cubicTo(QPointF(w * 0.35, h * 0.10), QPointF(w * 0.62, h * 0.95), QPointF(w - 16, h * 0.38))
        _paint_stroke(p, _Shape(self.kind, self.color, self.width_px, path))
        p.end()


class _Shape:
    """A stroke whose path is given directly, for the preview."""

    def __init__(self, kind, color, width, path):
        self.kind, self.color, self.width, self._path = kind, color, width, path

    def path(self):
        return self._path


class Swatch(QPushButton):
    """A colour, as a rounded square. Checked shows a ring."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        inset = 4 if self.isChecked() else 3
        p.setPen(QPen(QColor("#3a3a44"), 1))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), 5, 5)
        if self.isChecked():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        elif self.underMouse():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ACCENT, 1.5))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        p.end()


class OptionsPopup(QFrame):
    """Width and colour for the pen or the highlighter.

    Laid out width first, with the sample stroke between the label and the
    slider, then the colours as a grid of rounded squares.
    """

    changed = Signal(str, int)  # colour, width

    def __init__(self, kind: str, colors, widths, parent=None, columns: int = 6):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popup")
        self.setStyleSheet(POPUP_STYLE)
        self.kind = kind

        title = QLabel("Pen" if kind == "pen" else "Highlighter")
        title.setObjectName("PopupTitle")
        self.value = QLabel()
        self.value.setObjectName("PopupValue")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.value)

        self.preview = StrokePreview(kind)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(*widths)
        self.slider.valueChanged.connect(self._on_change)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.swatches: list[Swatch] = []
        for index, color in enumerate(colors):
            swatch = Swatch(color)
            swatch.clicked.connect(self._on_change)
            self.group.addButton(swatch)
            self.swatches.append(swatch)
            grid.addWidget(swatch, index // columns, index % columns)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        layout.addLayout(head)
        layout.addWidget(self.preview)
        layout.addWidget(self.slider)
        colours = QLabel("Colour")
        colours.setObjectName("PopupHint")
        layout.addWidget(colours)
        layout.addLayout(grid)
        self.setFixedWidth(max(5, columns) * 30 + 28 + (24 if columns < 6 else 0))

    def set_values(self, color: str, width: int) -> None:
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(int(width))
        self.slider.blockSignals(blocked)
        for swatch in self.swatches:
            swatch.setChecked(swatch.color.lower() == str(color).lower())
        self._sync_preview()

    def color(self) -> str:
        for swatch in self.swatches:
            if swatch.isChecked():
                return swatch.color
        return self.swatches[0].color

    def _on_change(self, *_args) -> None:
        self._sync_preview()
        self.changed.emit(self.color(), self.slider.value())

    def _sync_preview(self) -> None:
        self.preview.color = self.color()
        self.preview.width_px = self.slider.value()
        self.value.setText(f"{self.slider.value()} px")
        self.preview.update()


class RedactPopup(QFrame):
    """Blur or black out."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popup")
        self.setStyleSheet(POPUP_STYLE)
        title = QLabel("Redact")
        title.setObjectName("PopupTitle")
        self.black = QPushButton("Black out\nSolid black. Nothing survives.")
        self.blur = QPushButton("Blur\nSmeared. Layout can still show.")
        for button, mode in ((self.black, "black"), (self.blur, "blur")):
            button.setObjectName("Mode")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, m=mode: self._pick(m))
        group = QButtonGroup(self)
        group.addButton(self.black)
        group.addButton(self.blur)
        hint = QLabel("Drag over what to hide. Use Black out for passwords and hashes.")
        hint.setObjectName("PopupHint")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(self.black)
        layout.addWidget(self.blur)
        layout.addWidget(hint)
        self.setFixedWidth(280)

    def set_mode(self, mode: str) -> None:
        (self.blur if mode == "blur" else self.black).setChecked(True)

    def _pick(self, mode: str) -> None:
        self.changed.emit(mode)
        self.hide()


# -- the tool strip ---------------------------------------------------------------------
STRIP_STYLE = """
QWidget#ToolStrip { background: #1a1a1f; border: 1px solid #2c2c33; border-radius: 8px; }
QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 4px; color: #e6e6ec;
}
QToolButton:hover { background: #2a2a31; }
QToolButton:checked { background: #232a38; border: 1px solid #2f8cff; }
QToolButton#Undo {
    border: 1px solid #3a3a44; border-radius: 15px; background: #232329;
}
QToolButton#Undo:hover { border-color: #2f8cff; }
QToolButton#Undo:disabled { background: transparent; border-color: #26262c; }
QLabel#StripHint { color: #7c7c88; font-size: 11px; }
QFrame#StripRule { background: #2c2c33; }
"""

# Name, what it does, and whether it has options, for the hover box and the
# hint beside the strip.
TOOL_INFO = {
    "pen": ("Pen", "Draw freehand lines on the snip.", "colour and width"),
    "highlighter": ("Highlighter", "A see-through marker for picking out text; what is under it stays readable.", "colour and width"),
    "eraser": ("Eraser", "Drag across a pen line, highlight or redaction to remove the whole mark.", ""),
    "crop": ("Crop", "Drag the area of the snip to keep; the rest is cut away.", ""),
    "redact": ("Redact", "Drag over passwords, hashes or client details to hide them.", "blur or black out"),
}
HINTS = {
    None: "Left-click a tool to pick it up, right-click for its options. Changes save as you go.",
    "pen": "Pen: draw on the snip. Esc or click the pen again to put it down.",
    "highlighter": "Highlighter: drag over what matters. Esc or click it again to put it down.",
    "eraser": "Eraser: drag across a mark to remove it. Esc to put it down.",
    "crop": "Crop: drag the area to keep. Esc to put it down.",
    "redact": "Redact: drag over what to hide. Esc or click it again to put it down.",
}
NO_SNIP_HINT = "Take a snip to mark it up."


def tool_tooltip(kind: str) -> str:
    name, what, options = TOOL_INFO[kind]
    how = "Left-click: pick up or put down"
    if options:
        how += f". Right-click: {options}"
    return (f"<b>{name}</b><br>{html_escape(what)}"
            f"<br><span style='color:#9a9aa6'>{how}.</span>")


def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class AnnotToolbar(QWidget):
    """Pen, highlighter, eraser | crop, redact | undo.

    Left-click picks a tool up, and left-clicking the same tool again puts it
    down; Esc does the same from the window. Right-click opens a tool's
    options (width and colour, or blur and black out) and picks it up too, so
    the options always belong to the tool in hand. One tool at a time, shown
    in blue. Hovering a tool explains it, in its tooltip and in the hint
    beside the strip.
    """

    tool_changed = Signal(object)  # str or None
    prefs_changed = Signal(dict)
    undo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STRIP_STYLE)
        self.prefs = dict(DEFAULT_PREFS)
        self.tool: str | None = None
        self.buttons: dict[str, QToolButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(2)
        for group_index, group in enumerate((("pen", "highlighter", "eraser"), ("crop", "redact"))):
            if group_index:
                rule = QFrame()
                rule.setObjectName("StripRule")
                rule.setFixedSize(1, 22)
                layout.addSpacing(4)
                layout.addWidget(rule)
                layout.addSpacing(4)
            for kind in group:
                button = QToolButton()
                button.setCheckable(True)
                button.setIconSize(QSize(22, 22))
                button.setToolTip(tool_tooltip(kind))
                button.clicked.connect(lambda _c=False, k=kind: self._on_tool_clicked(k))
                button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda _pos, k=kind: self._on_tool_right_clicked(k)
                )
                button.installEventFilter(self)
                self.buttons[kind] = button
                layout.addWidget(button)

        layout.addSpacing(8)
        self.btn_undo = QToolButton()
        self.btn_undo.setObjectName("Undo")
        self.btn_undo.setIcon(tool_icon("undo"))
        self.btn_undo.setIconSize(QSize(18, 18))
        self.btn_undo.setFixedSize(30, 30)
        self.btn_undo.setToolTip("Undo the last change (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.btn_undo)

        layout.addSpacing(10)
        self.hint = QLabel(HINTS[None])
        self.hint.setObjectName("StripHint")
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.hint, 1)

        self.pen_popup = OptionsPopup("pen", PEN_COLORS, PEN_WIDTHS, columns=PEN_COLUMNS)
        self.pen_popup.changed.connect(lambda c, w: self._set_prefs(pen_color=c, pen_width=w))
        self.hl_popup = OptionsPopup(
            "highlighter", HIGHLIGHTER_COLORS, HIGHLIGHTER_WIDTHS, columns=HIGHLIGHTER_COLUMNS
        )
        self.hl_popup.changed.connect(lambda c, w: self._set_prefs(highlighter_color=c, highlighter_width=w))
        self.redact_popup = RedactPopup()
        self.redact_popup.changed.connect(lambda m: self._set_prefs(redact_mode=m))
        self._refresh_icons()
        self.set_undo_enabled(False)

    # -- state ------------------------------------------------------------------------
    def set_prefs(self, prefs: dict) -> None:
        self.prefs = sanitise_prefs(prefs)
        self._refresh_icons()

    def set_undo_enabled(self, on: bool) -> None:
        on = bool(on) and getattr(self, "_available", True)
        self.btn_undo.setEnabled(on)
        _fade(self.btn_undo, not on)

    def select(self, tool: str | None) -> None:
        self.tool = tool
        for kind, button in self.buttons.items():
            button.setChecked(kind == tool)
        self.hint.setText(self._hint_for(tool))
        self.tool_changed.emit(tool)

    def set_available(self, available: bool) -> None:
        """Usable only with a snip on screen; shown greyed out before that."""
        self._available = bool(available)
        for button in self.buttons.values():
            button.setEnabled(self._available)
            # The icons are drawn, so Qt's own disabled look barely shows;
            # fade them, so a strip that cannot be used looks it.
            _fade(button, not self._available)
        if not self._available:
            self.set_undo_enabled(False)
            if self.tool is not None:
                self.select(None)
        self.hint.setText(self._hint_for(self.tool))

    def _hint_for(self, tool: str | None) -> str:
        if not getattr(self, "_available", True):
            return NO_SNIP_HINT
        text = HINTS.get(tool, "")
        if tool == "redact":
            text += " Now: " + ("black out." if self.prefs["redact_mode"] == "black" else "blur.")
        return text

    def _on_tool_clicked(self, kind: str) -> None:
        """Left-click: pick the tool up, or put it down if it is in hand."""
        for popup in (self.pen_popup, self.hl_popup, self.redact_popup):
            popup.hide()
        self.select(None if self.tool == kind else kind)

    def _on_tool_right_clicked(self, kind: str) -> None:
        """Right-click: the tool's options, with the tool picked up."""
        if not self.buttons[kind].isEnabled():
            return
        if self.tool != kind:
            self.select(kind)
        popup = self._popup_for(kind)
        if popup is not None:
            self._open(popup, kind)
        else:
            # No options to show: say so, rather than doing nothing.
            name, what, _options = TOOL_INFO[kind]
            QToolTip.showText(QCursor.pos(), f"{name} has no options. {what}", self.buttons[kind])

    def eventFilter(self, watched, event):
        """Hovering a tool explains it in the hint beside the strip."""
        if getattr(self, "_available", True):
            for kind, button in self.buttons.items():
                if watched is button:
                    if event.type() == QEvent.Type.Enter:
                        name, what, options = TOOL_INFO[kind]
                        extra = f" Right-click for {options}." if options else ""
                        self.hint.setText(f"{name}: {what}{extra}")
                    elif event.type() == QEvent.Type.Leave:
                        self.hint.setText(self._hint_for(self.tool))
                    break
        return super().eventFilter(watched, event)

    def open_options(self, kind: str) -> None:
        popup = self._popup_for(kind)
        if popup is not None:
            self._open(popup, kind)

    def _popup_for(self, kind: str):
        return {"pen": self.pen_popup, "highlighter": self.hl_popup,
                "redact": self.redact_popup}.get(kind)

    def _open(self, popup, kind: str) -> None:
        if kind == "pen":
            popup.set_values(self.prefs["pen_color"], self.prefs["pen_width"])
        elif kind == "highlighter":
            popup.set_values(self.prefs["highlighter_color"], self.prefs["highlighter_width"])
        else:
            popup.set_mode(self.prefs["redact_mode"])
        button = self.buttons[kind]
        popup.adjustSize()
        popup.move(button.mapToGlobal(QPoint(0, button.height() + 6)))
        popup.show()

    def _set_prefs(self, **changes) -> None:
        self.prefs.update(changes)
        self.prefs = sanitise_prefs(self.prefs)
        self._refresh_icons()
        if self.tool == "redact":
            self.select("redact")
        self.prefs_changed.emit(dict(self.prefs))

    def _refresh_icons(self) -> None:
        self.buttons["pen"].setIcon(tool_icon("pen", self.prefs["pen_color"]))
        self.buttons["highlighter"].setIcon(tool_icon("highlighter", self.prefs["highlighter_color"]))
        self.buttons["eraser"].setIcon(tool_icon("eraser"))
        self.buttons["crop"].setIcon(tool_icon("crop"))
        self.buttons["redact"].setIcon(tool_icon("redact"))


def _fade(button, faded: bool) -> None:
    """Dim a button whose drawn icon would otherwise look usable when it is not."""
    effect = QGraphicsOpacityEffect(button)
    effect.setOpacity(0.35 if faded else 1.0)
    button.setGraphicsEffect(effect)


def sanitise_prefs(prefs) -> dict:
    """Clamp stored annotation settings to what the tools accept."""
    out = dict(DEFAULT_PREFS)
    if not isinstance(prefs, dict):
        return out
    for key, palette in (("pen_color", PEN_COLORS), ("highlighter_color", HIGHLIGHTER_COLORS)):
        value = str(prefs.get(key, out[key])).lower()
        if value in {c.lower() for c in palette}:
            out[key] = value
    for key, (low, high) in (("pen_width", PEN_WIDTHS), ("highlighter_width", HIGHLIGHTER_WIDTHS)):
        try:
            out[key] = min(high, max(low, int(prefs.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    if prefs.get("redact_mode") in ("blur", "black"):
        out["redact_mode"] = prefs["redact_mode"]
    return out
