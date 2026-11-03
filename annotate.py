"""Marking up a snip: pen, highlighter, eraser, shapes, labels, numbered steps,
callouts, spotlight, magnify, the evidence stamp, crop, redaction, undo, redo.

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
    Mark, Change      shapes, labels, steps, callouts, spotlight, magnify and the
                      stamp (0.11.0), and a move, resize or retype of one
    AnnotToolbar      the tool strip (TOOL_GROUPS), Quick redact, stamp, undo, redo
    OptionsPopup      width and colour for the pen and the highlighter
    MarkPopup         shape, colour, width or size for the 0.11.0 marks
    RedactPopup       blur or black out
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import threading

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import skins

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
    # 0.11.0: shapes, labels, steps, callouts and magnify share one colour.
    "mark_color": "#e81123",
    "shape_kind": "arrow",
    "shape_width": 4,
    "text_size": 18,
    "magnify_factor": 2,
}
SHAPE_KINDS = ("arrow", "line", "rect", "ellipse")
SHAPE_NAMES = {"arrow": "Arrow", "line": "Line", "rect": "Box", "ellipse": "Ellipse"}
TEXT_SIZES = (10, 48)
MAGNIFY_FACTORS = (2, 3, 4)
# Every kind of Mark (see below).
MARK_KINDS = (*SHAPE_KINDS, "label", "step", "callout", "spotlight", "magnify", "stamp")
# Marks that carry text you typed, and can have it edited.
TEXT_MARKS = ("label", "callout")
# How dark Spotlight makes everything outside the areas it keeps (0-255).
SPOTLIGHT_ALPHA = 150
# The stamp's text size, in screen pixels when it is added.
STAMP_SIZE = 13
# The square handles on a selected mark, in screen pixels.
HANDLE_SIZE = 9
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
# Zoom: each wheel notch multiplies the size by this; the closest view shows
# one image pixel as MAX_ZOOM_SCALE screen pixels.
ZOOM_STEP = 1.2
MAX_ZOOM_SCALE = 8.0

ACCENT = QColor("#2f8cff")  # the original look; painting asks accent() for the current skin


def accent() -> QColor:
    return QColor(skins.accent())
# The Text tool (0.10.0): word boxes, and the words picked out.
WORD_EDGE = QColor(47, 140, 255, 110)
WORD_FILL = QColor(47, 140, 255, 95)
# Tools whose cursor carries an icon badge beside the pointer.
BADGED_TOOLS = ("crop", "redact")
# Tools drawn in place of the pointer; the others use a system cursor.
DRAWN_CURSOR_TOOLS = ("pen", "highlighter", "eraser", "crop", "redact", "picker")
# The colour picker's loupe: this many image pixels across, each drawn this big.
LOUPE_PIXELS = 11
LOUPE_CELL = 10
# Tools that draw a mark by dragging (0.11.0).
DRAG_MARK_TOOLS = ("shape", "callout", "spotlight", "magnify")


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
    # Redactions added together by Quick redact share a batch number, so one
    # undo takes them all back. 0: drawn by hand, undone on its own.
    batch: int = 0


@dataclass
class Crop:
    id: int
    rect: QRect  # image pixels, in the original image


@dataclass
class Erase:
    id: int
    targets: frozenset  # ids of the marks hidden


@dataclass
class Restyle:
    """A redaction switched between black out and blur after it was drawn.

    An operation of its own rather than an edit to the redaction, so undo
    switches it back like any other change.
    """
    id: int
    target: int  # id of the Redact
    mode: str  # "blur" or "black"


@dataclass
class Mark:
    """A shape, label, step, callout, spotlight, magnifier or stamp (0.11.0).

    One operation type for every mark that can be moved after it is drawn.
    What the points mean depends on the kind:

        arrow, line        a -> b (the arrow's head is at b)
        rect, ellipse      the box a, b span
        spotlight          the area a, b span is kept bright
        magnify            the area a, b span, shown `factor` times larger at c
        label, stamp       text, its box's top left at a
        step               a numbered circle centred on a
        callout            an arrow to a, from a text box whose top left is b

    `width` is a line width and `size` a text size, both in image pixels.
    """
    id: int
    kind: str
    color: str
    a: QPointF
    b: QPointF
    width: float = 4.0
    size: float = 18.0
    text: str = ""
    number: int = 0
    c: QPointF | None = None
    factor: float = 2.0


@dataclass
class Change:
    """A mark moved, resized or retyped after it was made (0.11.0).

    An operation of its own, like Restyle, so undo puts it back. `fields`
    holds the new values: any of a, b, c (QPointF) and text.
    """
    id: int
    target: int
    fields: dict


class AnnotationDoc:
    """The original capture and the marks on it, in the order they were made."""

    def __init__(self, image: QImage):
        self.base = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.ops: list = []
        self._next = 1
        # Groups of operations taken back by undo, newest last, for redo.
        self._redo: list[list] = []

    # -- editing ------------------------------------------------------------------
    def new_id(self) -> int:
        ident = self._next
        self._next += 1
        return ident

    def add(self, op) -> None:
        self.ops.append(op)
        # Something new: what was undone can no longer be redone.
        self._redo.clear()

    def clone(self) -> "AnnotationDoc":
        """A separate doc with the same original and marks (the image is shared, not copied)."""
        twin = AnnotationDoc.__new__(AnnotationDoc)
        twin.base = self.base
        twin.ops = list(self.ops)
        twin._next = self._next
        twin._redo = [list(group) for group in getattr(self, "_redo", [])]
        return twin

    def undo(self) -> bool:
        if not self.ops:
            return False
        group = [self.ops.pop()]
        batch = getattr(group[0], "batch", 0)
        while batch and self.ops and getattr(self.ops[-1], "batch", 0) == batch:
            group.insert(0, self.ops.pop())
        self._redo.append(group)
        return True

    def redo(self) -> bool:
        """Put back what the last undo took away (a Quick redact batch as one)."""
        if not self._redo:
            return False
        self.ops.extend(self._redo.pop())
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self.ops)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # -- marks (0.11.0) -----------------------------------------------------------
    def effective(self, mark: "Mark") -> "Mark":
        """A mark as it is now: as made, with every later Change applied."""
        current = mark
        for op in self.ops:
            if isinstance(op, Change) and op.target == mark.id:
                current = _changed(current, op.fields)
        return current

    def marks(self, hidden=()) -> list:
        """The visible marks, as they are now, oldest first."""
        skip = self.erased() | set(hidden)
        return [self.effective(op) for op in self.ops if isinstance(op, Mark) and op.id not in skip]

    def mark_at(self, point: QPointF, radius: float):
        """The visible mark under `point` (image pixels), topmost first, or None."""
        for mark in reversed(self.marks()):
            if mark_hit(mark, point, radius):
                return mark
        return None

    def find(self, ident: int):
        for op in self.ops:
            if getattr(op, "id", None) == ident:
                return op
        return None

    def next_step(self) -> int:
        """The number the next numbered step gets: one more than the highest showing."""
        return max((m.number for m in self.marks() if m.kind == "step"), default=0) + 1

    @property
    def edited(self) -> bool:
        return bool(self.ops)

    def erased(self) -> set:
        hidden: set = set()
        for op in self.ops:
            if isinstance(op, Erase):
                hidden |= set(op.targets)
        return hidden

    def redact_mode(self, redact: "Redact") -> str:
        """A redaction's mode now: as drawn, or as last switched."""
        mode = redact.mode
        for op in self.ops:
            if isinstance(op, Restyle) and op.target == redact.id:
                mode = op.mode
        return mode

    def redaction_at(self, point: QPointF):
        """The visible redaction under `point` (image pixels), topmost first, or None."""
        hidden = self.erased()
        for op in reversed(self.ops):
            if isinstance(op, Redact) and op.id not in hidden and QRectF(op.rect).contains(point):
                return op
        return None

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
            elif isinstance(op, Mark):
                if mark_hit(self.effective(op), point, radius):
                    found.append(op.id)
        return found

    # -- rendering ------------------------------------------------------------------
    def render_full(self, hidden=()) -> QImage:
        """The original with every visible mark applied, before any crop."""
        image = self.base.copy()
        skip = self.erased() | set(hidden)
        painter = None
        spotlit = False
        for op in self.ops:
            if op.id in skip or isinstance(op, (Crop, Erase, Restyle, Change)):
                continue
            if isinstance(op, Mark):
                mark = self.effective(op)
                if mark.kind in ("spotlight", "magnify"):
                    # Both read the pixels so far, marks included.
                    if painter is not None:
                        painter.end()
                        painter = None
                    if mark.kind == "magnify":
                        _apply_magnify(image, mark)
                    elif not spotlit:
                        # Every spotlight at once, at the first one: two
                        # spotlights keep both areas bright rather than each
                        # dimming the other. Marks made later stay bright.
                        _apply_spotlight(image, [m for m in self.marks(hidden) if m.kind == "spotlight"])
                        spotlit = True
                    continue
                if painter is None:
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                paint_mark(painter, mark)
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
                _apply_redaction(image, op, self.redact_mode(op))
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


def _apply_redaction(image: QImage, op: Redact, mode: str | None = None) -> None:
    rect = op.rect.intersected(image.rect())
    if rect.isEmpty():
        return
    if (mode or op.mode) == "blur":
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


def colour_text(colour: QColor, as_rgb: bool = False) -> str:
    """#1e1e24, or rgb(30, 30, 36)."""
    if as_rgb:
        return f"rgb({colour.red()}, {colour.green()}, {colour.blue()})"
    return colour.name(QColor.NameFormat.HexRgb)


def _constrain(start: QPointF, end: QPointF, kind: str) -> QPointF:
    """Shift held: a line at a multiple of 45 degrees, or a square box."""
    dx, dy = end.x() - start.x(), end.y() - start.y()
    if kind in ("rect", "ellipse", "spotlight", "magnify"):
        side = max(abs(dx), abs(dy))
        return QPointF(start.x() + math.copysign(side, dx or 1), start.y() + math.copysign(side, dy or 1))
    length = math.hypot(dx, dy)
    if not length:
        return QPointF(end)
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return QPointF(start.x() + math.cos(angle) * length, start.y() + math.sin(angle) * length)


# -- marks: geometry and painting (0.11.0) -------------------------------------------------------
def _changed(mark: Mark, fields: dict) -> Mark:
    from dataclasses import replace

    allowed = {k: v for k, v in fields.items() if k in ("a", "b", "c", "text")}
    return replace(mark, **allowed)


def _font(size: float, bold: bool = True) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, int(round(size))))
    font.setBold(bold)
    return font


def text_box(mark: Mark) -> QRectF:
    """Where a label's, stamp's or callout's text box sits, in image pixels."""
    font = _font(mark.size, bold=mark.kind != "stamp")
    metrics = QFontMetricsF(font)
    lines = (mark.text or " ").split("\n")
    width = max(metrics.horizontalAdvance(line) for line in lines)
    height = metrics.height() * len(lines)
    pad = mark.size * 0.4
    corner = mark.b if mark.kind == "callout" else mark.a
    return QRectF(corner.x(), corner.y(), width + pad * 2, height + pad * 1.2)


def step_radius(mark: Mark) -> float:
    return max(6.0, mark.size * 0.8)


def magnify_rects(mark: Mark) -> tuple[QRectF, QRectF]:
    """(the area magnified, where the enlarged copy is shown)."""
    source = QRectF(mark.a, mark.b).normalized()
    corner = mark.c if mark.c is not None else source.topRight()
    return source, QRectF(corner.x(), corner.y(), source.width() * mark.factor, source.height() * mark.factor)


def mark_bounds(mark: Mark) -> QRectF:
    """Everything a mark covers, in image pixels."""
    if mark.kind in ("label", "stamp"):
        return text_box(mark)
    if mark.kind == "step":
        r = step_radius(mark)
        return QRectF(mark.a.x() - r, mark.a.y() - r, r * 2, r * 2)
    if mark.kind == "callout":
        return text_box(mark).united(QRectF(mark.a, mark.a).adjusted(-2, -2, 2, 2))
    if mark.kind == "magnify":
        source, inset = magnify_rects(mark)
        return source.united(inset)
    half = mark.width / 2
    return QRectF(mark.a, mark.b).normalized().adjusted(-half, -half, half, half)


def _outline(mark: Mark) -> QPainterPath:
    """The line a thin mark is drawn along, for hit testing."""
    path = QPainterPath()
    if mark.kind in ("arrow", "line"):
        path.moveTo(mark.a)
        path.lineTo(mark.b)
    elif mark.kind in ("rect", "spotlight"):
        path.addRect(QRectF(mark.a, mark.b).normalized())
    elif mark.kind == "ellipse":
        path.addEllipse(QRectF(mark.a, mark.b).normalized())
    return path


def mark_hit(mark: Mark, point: QPointF, radius: float) -> bool:
    """Whether `point` is on the mark: on its line, or inside a filled one."""
    if mark.kind in ("arrow", "line", "rect", "ellipse", "spotlight"):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(1.0, mark.width) + radius * 2)
        return stroker.createStroke(_outline(mark)).contains(point)
    if mark.kind == "callout":
        if text_box(mark).adjusted(-radius, -radius, radius, radius).contains(point):
            return True
        start = _box_edge_towards(text_box(mark), mark.a)
        return _segment_distance(point, start, mark.a) <= radius + mark.width
    if mark.kind == "magnify":
        source, inset = magnify_rects(mark)
        return inset.adjusted(-radius, -radius, radius, radius).contains(point) or (
            source.adjusted(-radius, -radius, radius, radius).contains(point)
        )
    return mark_bounds(mark).adjusted(-radius, -radius, radius, radius).contains(point)


def _ink_on(color: QColor) -> QColor:
    """Black or white, whichever reads on `color`."""
    light = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor("#111114") if light > 150 else QColor("#ffffff")


def _box_edge_towards(box: QRectF, target: QPointF) -> QPointF:
    """Where a line from the box's centre towards `target` leaves the box."""
    centre = box.center()
    dx, dy = target.x() - centre.x(), target.y() - centre.y()
    if dx == 0 and dy == 0:
        return centre
    tx = (box.width() / 2) / abs(dx) if dx else math.inf
    ty = (box.height() / 2) / abs(dy) if dy else math.inf
    t = min(tx, ty, 1.0)
    return QPointF(centre.x() + dx * t, centre.y() + dy * t)


def _arrow(painter: QPainter, start: QPointF, end: QPointF, color: QColor, width: float) -> None:
    """A line from start to end with a filled head at end."""
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    head = max(10.0, width * 3.6)
    length = math.hypot(end.x() - start.x(), end.y() - start.y())
    head = min(head, length * 0.6) if length else head
    # Stop the line inside the head, so a thick line has a sharp point.
    shaft_end = QPointF(end.x() - math.cos(angle) * head * 0.6, end.y() - math.sin(angle) * head * 0.6)
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(start, shaft_end)
    spread = math.radians(26)
    tip = QPolygonF([
        end,
        QPointF(end.x() - math.cos(angle - spread) * head, end.y() - math.sin(angle - spread) * head),
        QPointF(end.x() - math.cos(angle + spread) * head, end.y() - math.sin(angle + spread) * head),
    ])
    painter.setPen(QPen(color, max(1.0, width * 0.5), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(color)
    painter.drawPolygon(tip)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _paint_text_box(painter: QPainter, mark: Mark, fill: QColor, ink: QColor) -> None:
    box = text_box(mark)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(box, mark.size * 0.25, mark.size * 0.25)
    painter.setFont(_font(mark.size, bold=mark.kind != "stamp"))
    painter.setPen(ink)
    pad = mark.size * 0.4
    painter.drawText(box.adjusted(pad, pad * 0.6, -pad, -pad * 0.6),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), mark.text)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def paint_mark(painter: QPainter, mark: Mark) -> None:
    """Draw a mark in image coordinates (the painter may be scaled to the screen).

    Spotlight and magnify change pixels, so the doc applies those itself; here
    they are drawn as outlines, for a mark being drawn or moved.
    """
    color = QColor(mark.color)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if mark.kind == "arrow":
        _arrow(painter, mark.a, mark.b, color, mark.width)
    elif mark.kind in ("line", "rect", "ellipse"):
        pen = QPen(color, mark.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if mark.kind == "line":
            painter.drawLine(mark.a, mark.b)
        elif mark.kind == "rect":
            painter.drawRect(QRectF(mark.a, mark.b).normalized())
        else:
            painter.drawEllipse(QRectF(mark.a, mark.b).normalized())
    elif mark.kind == "label":
        _paint_text_box(painter, mark, color, _ink_on(color))
    elif mark.kind == "stamp":
        _paint_text_box(painter, mark, QColor(16, 16, 19, 205), QColor("#ffffff"))
    elif mark.kind == "callout":
        box = text_box(mark)
        _arrow(painter, _box_edge_towards(box, mark.a), mark.a, color, mark.width)
        _paint_text_box(painter, mark, color, _ink_on(color))
    elif mark.kind == "step":
        r = step_radius(mark)
        painter.setPen(QPen(QColor(255, 255, 255, 230), max(1.0, r * 0.12)))
        painter.setBrush(color)
        painter.drawEllipse(mark.a, r, r)
        painter.setFont(_font(r * 1.1))
        painter.setPen(_ink_on(color))
        painter.drawText(QRectF(mark.a.x() - r, mark.a.y() - r, r * 2, r * 2),
                         int(Qt.AlignmentFlag.AlignCenter), str(mark.number))
    elif mark.kind in ("spotlight", "magnify"):
        dash = QPen(color if mark.kind == "magnify" else QColor("#ffffff"), max(1.0, mark.width * 0.5),
                    Qt.PenStyle.DashLine)
        painter.setPen(dash)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if mark.kind == "spotlight":
            painter.drawRect(QRectF(mark.a, mark.b).normalized())
        else:
            source, inset = magnify_rects(mark)
            painter.drawRect(source)
            painter.drawRect(inset)
    painter.restore()


def _apply_spotlight(image: QImage, spots: list) -> None:
    """Dim everything outside the spotlit areas."""
    if not spots:
        return
    outside = QPainterPath()
    outside.addRect(QRectF(image.rect()))
    keep = QPainterPath()
    for mark in spots:
        keep.addRoundedRect(QRectF(mark.a, mark.b).normalized(), 6, 6)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.fillPath(outside.subtracted(keep.simplified()), QColor(0, 0, 0, SPOTLIGHT_ALPHA))
    painter.end()


def _facing_corners(source: QRectF, inset: QRectF) -> list:
    """The corner pairs that join the sides of two boxes facing each other."""
    dx = inset.center().x() - source.center().x()
    dy = inset.center().y() - source.center().y()
    if abs(dx) >= abs(dy):
        if dx >= 0:
            return [(source.topRight(), inset.topLeft()), (source.bottomRight(), inset.bottomLeft())]
        return [(source.topLeft(), inset.topRight()), (source.bottomLeft(), inset.bottomRight())]
    if dy >= 0:
        return [(source.bottomLeft(), inset.topLeft()), (source.bottomRight(), inset.topRight())]
    return [(source.topLeft(), inset.bottomLeft()), (source.topRight(), inset.bottomRight())]


def _apply_magnify(image: QImage, mark: Mark) -> None:
    """Show an area larger, at the inset's place, framed and joined to its source."""
    source, inset = magnify_rects(mark)
    area = source.toAlignedRect().intersected(image.rect())
    if area.isEmpty():
        return
    enlarged = image.copy(area).scaled(
        inset.size().toSize(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    color = QColor(mark.color)
    width = max(1.5, mark.width * 0.6)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Two faint lines joining the facing edges, under both frames.
    faint = QColor(color)
    faint.setAlpha(140)
    painter.setPen(QPen(faint, max(1.0, width * 0.6)))
    for start, end in _facing_corners(source, inset):
        painter.drawLine(start, end)
    painter.drawImage(inset.topLeft(), enlarged)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(color, width))
    painter.drawRect(source)
    painter.drawRect(inset)
    painter.end()


# How often the canvas looks for words read in the background, in ms.
OCR_POLL_MS = 40


def _png_of(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


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
    # From the right-click menu with no tool in hand.
    save_as_requested = Signal()
    copy_requested = Signal()
    # A short message for the status line: text copied, Quick redact done.
    notice = Signal(str)
    # Redo became available or ran out (0.11.0).
    redo_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(QSize(320, 200))
        self.setMouseTracking(True)
        # Clicking the snip gives it the keyboard, so Delete reaches the selected mark.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.doc: AnnotationDoc | None = None
        self.tool: str | None = None
        self.prefs = dict(DEFAULT_PREFS)
        # Rows added to the no-tool right-click menu by whoever hosts the
        # canvas, as (label, callback); the lab viewer adds Remove from lab.
        self.extra_menu_rows: list[tuple[str, object]] = []
        self.offer_save_as = True
        self._message = ""
        self._rendered: QImage | None = None
        self._pixmap: QPixmap | None = None
        self._live: Stroke | None = None
        self._drag_from: QPointF | None = None
        self._drag_to: QPointF | None = None
        self._erasing: set[int] = set()
        self._pointer: QPointF | None = None
        # Zoom is a multiple of the fitted size (1.0 = fitted); pan is how far
        # the image's centre sits from the canvas centre, in screen pixels.
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._panning_from: QPointF | None = None
        self._full_pixmap: QPixmap | None = None
        # The Text tool and Quick redact (0.10.0): the words read from the
        # snip as it looks now, which of them are picked, and what to do once
        # reading finishes. Reading runs in the background (see _read_text).
        self._words: list | None = None
        self._words_key = None
        self._reading_key = None
        self._text_error = ""
        self._picked: set[int] = set()
        self._pick_from: QPointF | None = None
        self._pick_to: QPointF | None = None
        self._after_reading: list = []
        # Reads in progress: plain dicts a reader thread fills in. The reader
        # never touches Qt. A Qt signal emitted from a Python thread crashed
        # PySide6 6.12 when the canvas went away mid-read (0.11.0), so the
        # canvas collects results on its own thread with a timer instead,
        # and a closed canvas takes its timer with it.
        self._ocr_boxes: list[dict] = []
        self._ocr_timer = QTimer(self)
        self._ocr_timer.setInterval(OCR_POLL_MS)
        self._ocr_timer.timeout.connect(self._collect_text)
        # Marks (0.11.0): the one being drawn, the one selected with the
        # Select tool, a move or resize in progress, and the text box open
        # for typing a label or a callout.
        self._mark_live: Mark | None = None
        self._selected: int | None = None
        self._grab: dict | None = None
        self._editor: QLineEdit | None = None
        self._editor_done = None
        # When the snip was taken, for the evidence stamp; None: now.
        self.stamp_time: str | None = None

    # -- content ----------------------------------------------------------------
    def load(self, image: QImage | None) -> None:
        self.load_doc(AnnotationDoc(image) if image is not None else None)

    def load_doc(self, doc: "AnnotationDoc | None") -> None:
        """Show `doc`. One opened from edits.py keeps every earlier mark erasable and undoable."""
        self.doc = doc
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._panning_from = None
        self._message = ""
        self._close_editor(commit=False)
        self._selected = None
        self._cancel_gesture()
        self._refresh()
        self.undo_changed.emit(bool(doc is not None and doc.can_undo))

    def set_message(self, text: str) -> None:
        """Text shown when there is no snip to show."""
        self._message = text
        if self.doc is None:
            self.update()

    def image(self) -> QImage | None:
        """The snip as it should be saved now."""
        return self.doc.render() if self.doc is not None else None

    def set_tool(self, tool: str | None) -> None:
        self._close_editor(commit=True)
        self._cancel_gesture()
        if tool != "text":
            self._picked = set()
        if tool != "select":
            self._selected = None
        self.tool = tool
        if tool == "text":
            self.read_text()
        self._sync_cursor()
        self.update()

    def _pointer_on_image(self) -> bool:
        return (
            self.tool is not None
            and self._pointer is not None
            and self._rendered is not None
            and self._visible().contains(self._pointer)
            and self._panning_from is None
        )

    def _sync_cursor(self) -> None:
        """Over the screenshot, the tool is drawn in place of the pointer.

        Everywhere else (the margins, the rest of the window) the ordinary
        arrow stays, so it is always clear where marks can go.
        """
        if self._panning_from is not None:
            shape = Qt.CursorShape.ClosedHandCursor
        elif (self.tool == "text" and self._pointer is not None and self._rendered is not None
              and self._visible().contains(self._pointer)):
            shape = Qt.CursorShape.IBeamCursor
        elif self._pointer_on_image() and self.tool in DRAWN_CURSOR_TOOLS:
            shape = Qt.CursorShape.BlankCursor
        elif self._pointer_on_image() and self.tool == "select":
            over = self._grab is not None or self._handle_at(self._pointer) or self._mark_under(self._pointer)
            shape = Qt.CursorShape.SizeAllCursor if over else Qt.CursorShape.ArrowCursor
        elif self._pointer_on_image():
            shape = Qt.CursorShape.CrossCursor
        elif (self.tool is None and self._pointer is not None and self.can_pan()
              and self._visible().contains(self._pointer)):
            shape = Qt.CursorShape.OpenHandCursor
        else:
            shape = Qt.CursorShape.ArrowCursor
        if self.cursor().shape() != shape:
            self.setCursor(shape)

    def undo(self) -> None:
        self._close_editor(commit=False)
        if self.doc is None or not self.doc.undo():
            return
        self._after_history_step()

    def redo(self) -> None:
        """Ctrl+Y: put back what undo took away."""
        self._close_editor(commit=False)
        if self.doc is None or not self.doc.redo():
            return
        self._after_history_step()

    def _after_history_step(self) -> None:
        if self._selected is not None and self._selected in self.doc.erased():
            self._selected = None
        if self._selected is not None and self.doc.find(self._selected) is None:
            self._selected = None
        self._refresh()
        self.undo_changed.emit(self.doc.can_undo)
        self.edited.emit()

    def _commit(self, *ops) -> None:
        """Add operations as one change the user made, and tell everyone."""
        for op in ops:
            self.doc.add(op)
        self._refresh()
        self.undo_changed.emit(self.doc.can_undo)
        self.edited.emit()

    # -- geometry -------------------------------------------------------------------
    def _area(self) -> QRectF:
        return QRectF(self.rect().adjusted(1, 1, -1, -1))

    def fit_scale(self) -> float:
        """Screen pixels per image pixel when fitted: whole, centred, never enlarged."""
        if self._rendered is None:
            return 1.0
        area = self._area()
        w, h = self._rendered.width(), self._rendered.height()
        return min(1.0, area.width() / max(1, w), area.height() / max(1, h))

    def max_zoom(self) -> float:
        fit = self.fit_scale() or 1.0
        return max(1.0, MAX_ZOOM_SCALE / fit)

    def zoom(self) -> float:
        """How far in from the fitted view: 1.0 is fitted."""
        return self._zoom

    def _target(self) -> QRectF:
        """Where the image is drawn, at the current zoom and pan.

        At zoom 1.0 that is fitted and centred. Zoomed in, the image can be
        moved, but never so far that a gap opens on a side it still covers.
        """
        if self._rendered is None:
            return QRectF()
        w, h = self._rendered.width(), self._rendered.height()
        area = self._area()
        scale = self.fit_scale() * self._zoom
        tw, th = w * scale, h * scale
        left = self._place(area.left(), area.width(), tw, self._pan.x())
        top = self._place(area.top(), area.height(), th, self._pan.y())
        return QRectF(left, top, tw, th)

    @staticmethod
    def _place(start: float, room: float, size: float, pan: float) -> float:
        """One axis of the image's position: centred if it fits, else panned within bounds."""
        centred = start + (room - size) / 2
        if size <= room:
            return centred
        return min(start, max(start + room - size, centred + pan))

    def _visible(self) -> QRectF:
        """The part of the canvas the image actually covers."""
        return self._target().intersected(self._area())

    def can_pan(self) -> bool:
        target = self._target()
        area = self._area()
        return target.width() > area.width() + 0.5 or target.height() > area.height() + 0.5

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """Zoom to `zoom` x the fitted size, keeping the image point under `anchor` still."""
        if self._rendered is None:
            return
        zoom = min(max(1.0, zoom), self.max_zoom())
        if abs(zoom - self._zoom) < 1e-6:
            return
        area = self._area()
        anchor = anchor if anchor is not None else area.center()
        before = self._target()
        old_scale = self.scale() or 1.0
        # The image point under the anchor, in rendered pixels.
        ix = (anchor.x() - before.x()) / old_scale
        iy = (anchor.y() - before.y()) / old_scale
        self._zoom = zoom
        new_scale = self.fit_scale() * zoom
        w, h = self._rendered.width() * new_scale, self._rendered.height() * new_scale
        left = anchor.x() - ix * new_scale
        top = anchor.y() - iy * new_scale
        self._pan = QPointF(left - (area.x() + (area.width() - w) / 2),
                            top - (area.y() + (area.height() - h) / 2))
        self._settle_pan()
        self._pixmap = None
        self._sync_cursor()
        self.update()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._pixmap = None
        self._sync_cursor()
        self.update()

    def _settle_pan(self) -> None:
        """Store the pan as actually drawn, so dragging past an edge does not build up."""
        if self._rendered is None:
            return
        area = self._area()
        target = self._target()
        self._pan = QPointF(
            target.x() - (area.x() + (area.width() - target.width()) / 2),
            target.y() - (area.y() + (area.height() - target.height()) / 2),
        )

    def wheelEvent(self, event):
        if self._rendered is None:
            return super().wheelEvent(event)
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return super().wheelEvent(event)
        self.set_zoom(self._zoom * (ZOOM_STEP ** steps), event.position())
        event.accept()

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
        else:
            hidden = set(self._erasing)
            if self._grab is not None:
                hidden.add(self._grab["id"])  # drawn live while it moves
            self._rendered = self.doc.render(hidden=hidden)
        self.redo_changed.emit(bool(self.doc is not None and self.doc.can_redo))
        self._pixmap = None
        self._full_pixmap = None
        # A crop changes the image's size; keep the view inside the new bounds.
        self._zoom = min(self._zoom, self.max_zoom()) if self._rendered is not None else 1.0
        self._settle_pan()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._pixmap = None
        self._settle_pan()

    # -- input --------------------------------------------------------------------------
    def _starts_pan(self, event) -> bool:
        """Middle-drag pans any time; left-drag pans with no tool in hand."""
        if self.doc is None or not self.can_pan():
            return False
        if event.button() == Qt.MouseButton.MiddleButton:
            return True
        return event.button() == Qt.MouseButton.LeftButton and self.tool is None

    def mouseDoubleClickEvent(self, event):
        # With no tool in hand, a double-click goes back to the fitted view.
        if self.tool is None and event.button() == Qt.MouseButton.LeftButton and self._zoom != 1.0:
            self.reset_zoom()
            return
        # Double-click a label or callout to change its text.
        if self.tool in ("select", "label") and self.doc is not None:
            mark = self._mark_under(event.position())
            if mark is not None and mark.kind in TEXT_MARKS:
                self.edit_text(mark)
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if self._starts_pan(event):
            self._panning_from = event.position()
            self._sync_cursor()
            return
        if self.doc is None or self.tool is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        point = self.to_image(pos)
        if self._editor is not None:
            # A click elsewhere finishes the text being typed.
            self._close_editor(commit=True)
            if self.tool in ("label", "callout"):
                return
        if self.tool == "text":
            self._pick_from = self._pick_to = point
            self.update()
            return
        if self.tool == "select":
            self._start_grab(pos, point)
            self.update()
            return
        if self.tool == "label":
            self._open_editor(self._clamp(point), lambda text, at=self._clamp(point): self._add_label(at, text))
            return
        if self.tool == "step":
            self._add_step(self._clamp(point))
            return
        if self.tool == "picker":
            as_rgb = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.copy_colour(point, as_rgb=as_rgb)
            return
        if self.tool in DRAG_MARK_TOOLS:
            start = self._clamp(point)
            self._mark_live = self._new_mark(start, start)
            self.update()
            return
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
        if self._panning_from is not None:
            self._pan += pos - self._panning_from
            self._panning_from = pos
            self._settle_pan()
            self.update()
            return
        self._sync_cursor()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._pick_from is not None:
            self._pick_to = self.to_image(pos)
        elif self._grab is not None:
            self._move_grab(self.to_image(pos), shift)
        elif self._mark_live is not None:
            end = self._clamp(self.to_image(pos))
            if shift:
                end = _constrain(self._mark_live.a, end, self._mark_live.kind)
            self._mark_live.b = end
        elif self._live is not None:
            point = self.to_image(pos)
            if shift and self._live.kind == "pen":
                # Shift: a straight line from where the stroke started.
                self._live.points = [self._live.points[0], _constrain(self._live.points[0], point, "line")]
            else:
                self._live.points.append(point)
        elif self.tool == "eraser" and event.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(pos)
        elif self._drag_from is not None:
            self._drag_to = self._clamp(self.to_image(pos))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._panning_from is not None and event.button() in (
            Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton
        ):
            self._panning_from = None
            self._sync_cursor()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.doc is None:
            return super().mouseReleaseEvent(event)
        if self._pick_from is not None:
            self._finish_pick(event.modifiers())
            return
        if self._grab is not None:
            self._finish_grab()
            return
        if self._mark_live is not None:
            self._finish_mark()
            return
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

    # -- the right-click menu ------------------------------------------------------
    def context_actions(self, pos: QPointF) -> list:
        """What a right-click at `pos` offers, as (label, callback, checked) rows.

        Over a redaction: switch it between black out and blur, any time.
        Anywhere on the snip: Save as and Copy, with or without a tool in hand.
        Before 0.9.2 a tool in hand hid them; every tool draws with the left
        button only, so the right-click menu never got in its way, and having
        to put the pen down just to copy the marked-up snip was the wrong way
        round.
        """
        if self.doc is None or self._rendered is None or not self._target().contains(pos):
            return []
        rows = []
        mark = self._mark_under(pos)
        if mark is not None:
            if mark.kind in TEXT_MARKS:
                rows.append(("Edit text...", lambda m=mark: self.edit_text(m), None))
            rows.append(("Delete this mark", lambda m=mark: self.delete_mark(m.id), None))
            rows.append(None)
        redaction = self.doc.redaction_at(self.to_image(pos))
        if redaction is not None:
            mode = self.doc.redact_mode(redaction)
            rows.append(("Black out this redaction", lambda r=redaction: self.restyle(r, "black"), mode == "black"))
            rows.append(("Blur this redaction", lambda r=redaction: self.restyle(r, "blur"), mode == "blur"))
        if self.tool == "text":
            if rows:
                rows.append(None)
            if self._picked:
                rows.append(("Copy selected text", lambda: self.copy_text(selected=True), None))
            rows.append(("Copy all text", lambda: self.copy_text(selected=False), None))
            rows.append(("Quick redact...", self.quick_redact, None))
        if rows:
            rows.append(None)  # a separator
        if self.offer_save_as:
            rows.append(("Save as...", self.save_as_requested.emit, None))
        rows.append(("Copy", self.copy_requested.emit, None))
        for label, callback in self.extra_menu_rows:
            rows.append((label, callback, None))
        return rows

    def restyle(self, redaction: "Redact", mode: str) -> None:
        if self.doc is None or self.doc.redact_mode(redaction) == mode:
            return
        self.doc.add(Restyle(self.doc.new_id(), redaction.id, mode))
        self._refresh()
        self.undo_changed.emit(self.doc.can_undo)
        self.edited.emit()

    def contextMenuEvent(self, event):
        rows = self.context_actions(QPointF(event.pos()))
        if not rows:
            return super().contextMenuEvent(event)
        menu = QMenu(self)
        menu.setStyleSheet(skins.style(MENU_STYLE))
        for row in rows:
            if row is None:
                menu.addSeparator()
                continue
            label, callback, checked = row
            action = menu.addAction(label)
            if checked is not None:
                action.setCheckable(True)
                action.setChecked(checked)
            action.triggered.connect(lambda _c=False, cb=callback: cb())
        menu.exec(event.globalPos())

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
        self._pick_from = self._pick_to = None
        self._live = None
        self._mark_live = None
        if self._grab is not None:
            self._grab = None
            self._refresh()
        self._drag_from = self._drag_to = None
        if self._erasing:
            self._erasing = set()
            if self.doc is not None:
                self._rendered = self.doc.render()

    # -- the colour picker (0.12.0) -------------------------------------------------------
    def colour_at(self, point: QPointF) -> QColor | None:
        """The colour of the snip, as it looks now, at `point` (image pixels)."""
        if self._rendered is None or self.doc is None:
            return None
        crop = self.doc.crop_rect()
        x, y = int(math.floor(point.x())) - crop.x(), int(math.floor(point.y())) - crop.y()
        if not (0 <= x < self._rendered.width() and 0 <= y < self._rendered.height()):
            return None
        return QColor(self._rendered.pixel(x, y))

    def copy_colour(self, point: QPointF, as_rgb: bool = False) -> str:
        """Put a pixel's colour on the clipboard: #rrggbb, or rgb(r, g, b) with Shift."""
        colour = self.colour_at(point)
        if colour is None:
            return ""
        text = colour_text(colour, as_rgb)
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        other = colour_text(colour, not as_rgb)
        self.notice.emit(f"Copied {text}  ({other})")
        return text

    def _paint_loupe(self, painter: QPainter, target: QRectF) -> None:
        """A magnified square of pixels around the pointer, with the colour under it."""
        pos = self._pointer
        point = self.to_image(pos)
        colour = self.colour_at(point)
        if colour is None:
            return
        crop = self.doc.crop_rect()
        cx, cy = int(math.floor(point.x())) - crop.x(), int(math.floor(point.y())) - crop.y()
        half = LOUPE_PIXELS // 2
        side = LOUPE_PIXELS * LOUPE_CELL
        label_h = 22
        box = QRectF(pos.x() + 18, pos.y() + 18, side, side + label_h)
        # Keep the loupe on the canvas: flip to the other side of the pointer near an edge.
        if box.right() > self.width() - 2:
            box.moveRight(pos.x() - 18)
        if box.bottom() > self.height() - 2:
            box.moveBottom(pos.y() - 18)
        painter.save()
        painter.setClipping(False)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(box.adjusted(-2, -2, 2, 2), QColor(16, 16, 19, 235))
        for row in range(LOUPE_PIXELS):
            for col in range(LOUPE_PIXELS):
                x, y = cx - half + col, cy - half + row
                inside = 0 <= x < self._rendered.width() and 0 <= y < self._rendered.height()
                fill = QColor(self._rendered.pixel(x, y)) if inside else QColor(40, 40, 46)
                painter.fillRect(QRectF(box.x() + col * LOUPE_CELL, box.y() + row * LOUPE_CELL,
                                        LOUPE_CELL, LOUPE_CELL), fill)
        middle = QRectF(box.x() + half * LOUPE_CELL, box.y() + half * LOUPE_CELL, LOUPE_CELL, LOUPE_CELL)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawRect(middle.adjusted(-1, -1, 0, 0))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(middle)
        painter.setPen(QPen(QColor(255, 255, 255, 110), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(box.adjusted(-2, -2, 2, 2))
        label = QRectF(box.x(), box.y() + side, side, label_h)
        swatch = QRectF(label.x() + 5, label.y() + 5, label_h - 10, label_h - 10)
        painter.fillRect(swatch, colour)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(label.adjusted(label_h - 2, 0, 0, 0),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         colour_text(colour, False).upper())
        # A small crosshair where the pointer is.
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.drawLine(QPointF(pos.x() - 7, pos.y()), QPointF(pos.x() + 7, pos.y()))
        painter.drawLine(QPointF(pos.x(), pos.y() - 7), QPointF(pos.x(), pos.y() + 7))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawLine(QPointF(pos.x() - 7, pos.y()), QPointF(pos.x() + 7, pos.y()))
        painter.drawLine(QPointF(pos.x(), pos.y() - 7), QPointF(pos.x(), pos.y() + 7))
        painter.restore()

    # -- marks: drawing (0.11.0) ----------------------------------------------------------
    def _image_size(self, screen_px: float) -> float:
        """A size picked in screen pixels, in image pixels at the current zoom."""
        return max(0.5, float(screen_px) / (self.scale() or 1.0))

    def _new_mark(self, a: QPointF, b: QPointF) -> Mark:
        tool = self.tool
        kind = self.prefs.get("shape_kind", "arrow") if tool == "shape" else tool
        mark = Mark(
            id=self.doc.new_id(), kind=kind, color=self.prefs.get("mark_color", "#e81123"),
            a=QPointF(a), b=QPointF(b),
            width=self._image_size(self.prefs.get("shape_width", 4)),
            size=self._image_size(self.prefs.get("text_size", 18)),
        )
        if kind == "magnify":
            mark.factor = float(self.prefs.get("magnify_factor", 2))
        return mark

    def _finish_mark(self) -> None:
        mark, self._mark_live = self._mark_live, None
        span = math.hypot(mark.b.x() - mark.a.x(), mark.b.y() - mark.a.y()) * self.scale()
        boxy = mark.kind in ("rect", "ellipse", "spotlight", "magnify")
        if boxy:
            r = QRectF(mark.a, mark.b).normalized()
            span = min(r.width(), r.height()) * self.scale()
        if span < MIN_DRAG:
            self.update()
            return
        if mark.kind == "magnify":
            mark.c = self._place_inset(QRectF(mark.a, mark.b).normalized(), mark.factor)
        if mark.kind == "callout":
            # The drag ran from what to point at to where the words go.
            self.update()
            self._open_editor(mark.b, lambda text, m=mark: self._add_callout(m, text))
            return
        self._commit(mark)

    def _place_inset(self, source: QRectF, factor: float) -> QPointF:
        """Where a magnified copy goes: beside its source, inside the snip, if it fits."""
        crop = QRectF(self.doc.crop_rect())
        w, h = source.width() * factor, source.height() * factor
        gap = max(8.0, 12.0 / (self.scale() or 1.0))
        candidates = [
            QPointF(source.right() + gap, source.top()),
            QPointF(source.left() - gap - w, source.top()),
            QPointF(source.left(), source.bottom() + gap),
            QPointF(source.left(), source.top() - gap - h),
        ]
        for corner in candidates:
            box = QRectF(corner.x(), corner.y(), w, h)
            if crop.contains(box):
                return corner
        # Nowhere clear: the corner of the snip farthest from the source.
        x = crop.left() + gap if source.center().x() > crop.center().x() else crop.right() - gap - w
        y = crop.top() + gap if source.center().y() > crop.center().y() else crop.bottom() - gap - h
        return QPointF(max(crop.left(), x), max(crop.top(), y))

    def _add_label(self, at: QPointF, text: str) -> None:
        if not text.strip():
            return
        mark = self._new_mark(at, at)
        mark.kind, mark.text = "label", text
        self._keep_inside(mark)
        self._commit(mark)

    def _add_callout(self, mark: Mark, text: str) -> None:
        if not text.strip():
            self.update()
            return
        mark.text = text
        self._keep_inside(mark)
        self._commit(mark)

    def _keep_inside(self, mark: Mark) -> None:
        """Slide a new text box back onto the snip if it would run off an edge."""
        crop = QRectF(self.doc.crop_rect())
        box = text_box(mark)
        dx = min(0.0, crop.right() - box.right())
        dx = max(dx, crop.left() - box.left())
        dy = min(0.0, crop.bottom() - box.bottom())
        dy = max(dy, crop.top() - box.top())
        if dx or dy:
            shift = QPointF(dx, dy)
            if mark.kind == "callout":
                mark.b = mark.b + shift
            else:
                mark.a = mark.a + shift
                mark.b = QPointF(mark.a)

    def _add_step(self, at: QPointF) -> None:
        mark = self._new_mark(at, at)
        mark.kind, mark.number = "step", self.doc.next_step()
        self._commit(mark)

    def add_stamp(self) -> None:
        """The evidence stamp: when the snip was taken and on which machine, bottom right."""
        if self.doc is None:
            return
        import socket
        from datetime import datetime

        when = self.stamp_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            host = socket.gethostname() or "unknown host"
        except OSError:
            host = "unknown host"
        mark = Mark(self.doc.new_id(), "stamp", "#ffffff", QPointF(), QPointF(),
                    size=self._image_size(STAMP_SIZE), text=f"{when}  |  {host}")
        box = text_box(mark)
        crop = QRectF(self.doc.crop_rect())
        margin = self._image_size(8)
        mark.a = QPointF(max(crop.left(), crop.right() - box.width() - margin),
                         max(crop.top(), crop.bottom() - box.height() - margin))
        mark.b = QPointF(mark.a)
        self._commit(mark)
        self.notice.emit("Stamped with the time and this machine's name. Select it to move it.")

    def delete_mark(self, ident: int) -> None:
        if self.doc is None or self.doc.find(ident) is None or ident in self.doc.erased():
            return
        if self._selected == ident:
            self._selected = None
        self._commit(Erase(self.doc.new_id(), frozenset({ident})))

    def delete_selected(self) -> bool:
        """Delete: remove the selected mark. False when nothing is selected."""
        if self._selected is None or self.tool != "select":
            return False
        self.delete_mark(self._selected)
        return True

    def selected_mark(self):
        if self.doc is None or self._selected is None or self._selected in self.doc.erased():
            return None
        op = self.doc.find(self._selected)
        return self.doc.effective(op) if isinstance(op, Mark) else None

    # -- marks: typing ---------------------------------------------------------------------
    def edit_text(self, mark: Mark) -> None:
        """Change a label's or callout's words; emptied, the mark goes."""
        corner = mark.b if mark.kind == "callout" else mark.a

        def done(text: str, ident=mark.id, old=mark.text) -> None:
            if not text.strip():
                self.delete_mark(ident)
            elif text != old:
                self._commit(Change(self.doc.new_id(), ident, {"text": text}))

        self._open_editor(corner, done, mark.text, size=mark.size * self.scale())

    def _open_editor(self, at: QPointF, done, text: str = "", size: float | None = None) -> None:
        """A text box on the snip at `at` (image pixels); Enter keeps, Esc drops."""
        self._close_editor(commit=True)
        # One text box per canvas, shown and hidden, never deleted: a box
        # deleted later (deleteLater) can outlive the canvas that owned it.
        editor = getattr(self, "_editor_widget", None)
        if editor is None:
            editor = self._editor_widget = QLineEdit(self)
            editor.setObjectName("MarkEditor")
            editor.setPlaceholderText("Type, then Enter")
            editor.setMinimumWidth(180)
            editor.returnPressed.connect(lambda: self._close_editor(commit=True))
        editor.setText(text)
        px = int(round(size or self.prefs.get("text_size", 18)))
        editor.setStyleSheet(
            f"QLineEdit#MarkEditor {{ font-size: {max(10, px)}px; font-weight: 600; "
            "background: rgba(16,16,19,230); color: #ffffff; "
            f"border: 1px solid {accent().name()}; border-radius: 4px; padding: 2px 6px; }}"
        )
        editor.adjustSize()
        spot = self.to_widget(at).toPoint()
        spot.setX(min(max(0, spot.x()), max(0, self.width() - editor.width())))
        spot.setY(min(max(0, spot.y()), max(0, self.height() - editor.height())))
        editor.move(spot)
        editor.installEventFilter(self)
        self._editor, self._editor_done = editor, done
        editor.show()
        editor.setFocus()

    def _close_editor(self, commit: bool) -> None:
        editor, done = self._editor, self._editor_done
        if editor is None:
            return
        self._editor = self._editor_done = None
        text = editor.text()
        editor.removeEventFilter(self)
        editor.hide()
        self.setFocus()
        if commit and done is not None and self.doc is not None:
            done(text)
        self.update()

    def editing_text(self) -> bool:
        return self._editor is not None

    def eventFilter(self, watched, event):
        if watched is self._editor and self._editor is not None:
            if event.type() == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Escape:
                event.accept()  # Esc belongs to the text box, not the window
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._close_editor(commit=False)
                return True
            if event.type() == QEvent.Type.FocusOut:
                self._close_editor(commit=True)
                return False
        return super().eventFilter(watched, event)

    # -- marks: selecting, moving, resizing --------------------------------------------
    def _mark_under(self, pos: QPointF):
        if self.doc is None:
            return None
        return self.doc.mark_at(self.to_image(pos), ERASER_RADIUS / (self.scale() or 1.0))

    def _handles(self, mark: Mark) -> dict:
        """The selected mark's handles: name -> point (image pixels)."""
        if mark.kind in ("arrow", "line", "rect", "ellipse", "spotlight", "magnify"):
            return {"a": mark.a, "b": mark.b}
        if mark.kind == "callout":
            return {"a": mark.a}
        return {}

    def _handle_at(self, pos: QPointF) -> str | None:
        mark = self.selected_mark()
        if mark is None:
            return None
        reach = HANDLE_SIZE
        for name, point in self._handles(mark).items():
            spot = self.to_widget(point)
            if abs(spot.x() - pos.x()) <= reach and abs(spot.y() - pos.y()) <= reach:
                return name
        return None

    def _start_grab(self, pos: QPointF, point: QPointF) -> None:
        handle = self._handle_at(pos)
        mark = self.selected_mark() if handle else self._mark_under(pos)
        if mark is None:
            self._selected = None
            return
        self._selected = mark.id
        part = handle or "move"
        if part == "move" and mark.kind == "magnify":
            # The enlarged copy moves on its own; the area it shows moves the whole mark.
            _source, inset = magnify_rects(mark)
            if inset.contains(point):
                part = "inset"
        if part == "move" and mark.kind == "callout" and text_box(mark).contains(point):
            part = "box"
        self._grab = {"id": mark.id, "part": part, "start": point, "mark": mark, "now": mark}
        self._refresh()

    def _move_grab(self, point: QPointF, shift: bool) -> None:
        grab = self._grab
        mark, part = grab["mark"], grab["part"]
        d = point - grab["start"]
        fields: dict = {}
        if part == "move":
            fields = {"a": mark.a + d, "b": mark.b + d}
            if mark.c is not None:
                fields["c"] = mark.c + d
        elif part == "inset":
            fields = {"c": mark.c + d}
        elif part == "box":
            fields = {"b": mark.b + d}
        else:  # a handle
            target = self._clamp(point)
            other = mark.b if part == "a" else mark.a
            if shift and mark.kind != "callout":
                target = _constrain(other, target, mark.kind)
            fields = {part: target}
        grab["fields"] = fields
        grab["now"] = _changed(mark, fields)

    def _finish_grab(self) -> None:
        grab, self._grab = self._grab, None
        fields = grab.get("fields")
        if fields and any(grab["mark"].__dict__.get(k) != v for k, v in fields.items()):
            self._commit(Change(self.doc.new_id(), grab["id"], fields))
        else:
            self._refresh()

    def _paint_marks_overlay(self, painter: QPainter) -> None:
        """The mark being drawn or moved, and the selected mark's frame and handles."""
        transform = QTransform()
        crop = self.doc.crop_rect()
        target = self._target()
        s = self.scale()
        transform.translate(target.x() - crop.x() * s, target.y() - crop.y() * s)
        transform.scale(s, s)
        live = self._mark_live or (self._grab["now"] if self._grab is not None else None)
        if live is not None:
            painter.save()
            painter.setTransform(transform, True)
            paint_mark(painter, live)
            painter.restore()
        mark = live if self._grab is not None else self.selected_mark()
        if mark is None or self.tool != "select":
            return
        frame = QRectF(self.to_widget(mark_bounds(mark).topLeft()),
                       self.to_widget(mark_bounds(mark).bottomRight())).adjusted(-4, -4, 4, 4)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 150), 2.5))
        painter.drawRect(frame)
        painter.setPen(QPen(accent(), 1, Qt.PenStyle.DashLine))
        painter.drawRect(frame)
        half = HANDLE_SIZE / 2
        for point in self._handles(mark).values():
            spot = self.to_widget(point)
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
            painter.setBrush(QColor("#ffffff"))
            painter.drawRect(QRectF(spot.x() - half, spot.y() - half, HANDLE_SIZE, HANDLE_SIZE))
        painter.restore()

    # -- the Text tool and Quick redact (0.10.0) ----------------------------------------
    def _text_key(self):
        """What the words read belong to: this doc, with exactly these marks."""
        if self.doc is None:
            return None
        return (id(self.doc), tuple(op.id for op in self.doc.ops))

    def read_text(self, then=None) -> None:
        """Read the words in the snip as it looks now, in the background.

        `then` runs once they are ready (straight away when they already are).
        Nothing is read while the snip is unchanged since the last time.
        """
        key = self._text_key()
        if key is None:
            return
        if then is not None:
            self._after_reading.append(then)
        if self._words is not None and self._words_key == key:
            self._run_after_reading()
            return
        if self._reading_key == key:
            return  # already on it
        self._reading_key = key
        self._text_error = ""
        png = _png_of(self.doc.render_full())
        box: dict = {}
        self._ocr_boxes.append(box)

        def work():
            import ocr

            try:
                words, error = ocr.recognise(png), ""
            except Exception as exc:  # noqa: BLE001 - shown to the user, never raised
                words, error = None, str(exc)
            box["result"] = (key, words, error)  # a plain dict: no Qt from this thread

        threading.Thread(target=work, name="shadowsnip-ocr", daemon=True).start()
        self._ocr_timer.start()
        self.update()

    def _collect_text(self) -> None:
        """The timer: hand on any read that has finished, in the order they finish."""
        for box in list(self._ocr_boxes):
            if "result" in box:
                self._ocr_boxes.remove(box)
                self._on_text_read(*box["result"])
        if not self._ocr_boxes:
            self._ocr_timer.stop()

    def _on_text_read(self, key, words, error) -> None:
        if key != self._reading_key:
            return  # the snip changed while it was being read; that read is stale
        self._reading_key = None
        if words is None:
            self._text_error = error or "No text could be read."
            self._after_reading.clear()
            self.notice.emit(self._text_error)
        else:
            self._words, self._words_key = words, key
            self._picked = set()
        self.update()
        if self._text_key() != key:
            self.read_text()  # changed meanwhile: read the new state
            return
        self._run_after_reading()

    def _run_after_reading(self) -> None:
        pending, self._after_reading = self._after_reading, []
        for callback in pending:
            callback()

    @property
    def reading_text(self) -> bool:
        return self._reading_key is not None

    def visible_words(self) -> list:
        """The words read, inside the crop (what is on the saved snip)."""
        if self._words is None or self.doc is None or self._words_key != self._text_key():
            return []
        crop = QRectF(self.doc.crop_rect())
        return [w for w in self._words if crop.contains(QPointF(w.x + w.w / 2, w.y + w.h / 2))]

    def _finish_pick(self, modifiers) -> None:
        start, end = self._pick_from, self._pick_to
        self._pick_from = self._pick_to = None
        words = self.visible_words()
        adding = bool(modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        picked = set(self._picked) if adding else set()
        rect = QRectF(start, end).normalized()
        if rect.width() * self.scale() < MIN_DRAG and rect.height() * self.scale() < MIN_DRAG:
            # A click: the word under it, or nothing.
            for word in words:
                if QRectF(word.x, word.y, word.w, word.h).adjusted(-2, -2, 2, 2).contains(start):
                    picked ^= {id(word)} if adding else {id(word)}
                    break
        else:
            for word in words:
                if rect.intersects(QRectF(word.x, word.y, word.w, word.h)):
                    picked.add(id(word))
        self._picked = picked
        self.update()

    def pick_all_text(self) -> None:
        self._picked = {id(w) for w in self.visible_words()}
        self.update()

    def has_picked_text(self) -> bool:
        return bool(self._picked)

    def picked_text(self) -> str:
        import ocr

        return ocr.text_of([w for w in self.visible_words() if id(w) in self._picked])

    def copy_text(self, selected: bool = True) -> None:
        """Put the picked words (or all of them) on the clipboard as text."""
        def go():
            import ocr

            words = self.visible_words()
            if selected and self._picked:
                words = [w for w in words if id(w) in self._picked]
            text = ocr.text_of(words)
            if not text.strip():
                self.notice.emit("No text found in this snip")
                return
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            lines = text.count("\n") + 1
            self.notice.emit(
                f"Copied {len(words)} word{'s' if len(words) != 1 else ''} "
                f"({lines} line{'s' if lines != 1 else ''}) as text"
            )

        self.read_text(then=go)

    def quick_redact(self) -> None:
        """Find emails, phone numbers, hashes, passwords and keys, and offer to hide them."""
        if self.doc is None:
            return
        self.notice.emit("Reading the text to find what to hide...")
        self.read_text(then=self._offer_quick_redact)

    def _offer_quick_redact(self) -> None:
        import ocr
        from quickredact import QuickRedactDialog

        found = ocr.find_sensitive(self.visible_words())
        if not found:
            self.notice.emit("Quick redact found nothing to hide in this snip")
            return
        dialog = QuickRedactDialog(found, self.prefs.get("quick_redact"), self.window())
        if dialog.exec() != dialog.DialogCode.Accepted:
            self.notice.emit("Quick redact cancelled; nothing was hidden")
            return
        kinds = dialog.chosen_kinds()
        self.prefs["quick_redact"] = sorted(kinds)
        chosen = [f for f in found if f.kind in kinds]
        self.add_redactions([box for f in chosen for box in f.boxes])
        self.notice.emit(
            f"Quick redact hid {len(chosen)} item{'s' if len(chosen) != 1 else ''}. "
            "Erase any you want back, or undo them all at once (Ctrl+Z)."
        )

    def add_redactions(self, boxes) -> int:
        """Cover each (x, y, w, h) box; all of them undo together. Returns how many."""
        if self.doc is None or not boxes:
            return 0
        crop = self.doc.crop_rect()
        batch = self.doc.new_id()
        added = 0
        for x, y, w, h in boxes:
            rect = QRect(int(x), int(y), int(w), int(h)).intersected(self.doc.base.rect())
            if rect.isEmpty() or not rect.intersects(crop):
                continue
            self.doc.add(Redact(self.doc.new_id(), rect, self.prefs.get("redact_mode", "black"), batch))
            added += 1
        if added:
            self._refresh()
            self.undo_changed.emit(self.doc.can_undo)
            self.edited.emit()
        return added

    def _paint_words(self, painter: QPainter) -> None:
        """The Text tool: every word read, outlined; the picked ones filled."""
        painter.save()
        painter.setClipRect(self._visible())
        message = ""
        if self.reading_text:
            message = "Reading the text..."
        elif self._text_error:
            message = self._text_error
        else:
            words = self.visible_words()
            if self._words is not None and not words:
                message = "No text found in this snip"
            for word in words:
                top_left = self.to_widget(QPointF(word.x, word.y))
                bottom_right = self.to_widget(QPointF(word.x + word.w, word.y + word.h))
                box = QRectF(top_left, bottom_right).adjusted(-1, -1, 1, 1)
                if id(word) in self._picked:
                    painter.fillRect(box, WORD_FILL)
                painter.setPen(QPen(WORD_EDGE, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(box)
        if self._pick_from is not None and self._pick_to is not None:
            rect = QRectF(self.to_widget(self._pick_from), self.to_widget(self._pick_to)).normalized()
            painter.setPen(QPen(accent(), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
        if message:
            metrics = painter.fontMetrics()
            box = QRectF(0, 0, min(self.width() - 40, metrics.horizontalAdvance(message) + 24),
                         metrics.height() + 12)
            box.moveCenter(QPointF(self._visible().center().x(), self._visible().top() + 30))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 16, 19, 220))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QColor("#e6e6ec"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message)
        painter.restore()

    # -- painting -----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), skins.color("#101013"))
        painter.setPen(QPen(skins.color("#2c2c33"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self._rendered is None:
            painter.setPen(skins.color("#9a9aa6"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return

        target = self._target()
        visible = self._visible()
        scale = self.scale()
        painter.save()
        painter.setClipRect(self._area())
        if scale < 1.0:
            # Smaller than life: scale once, smoothly, and reuse while only
            # the position changes.
            if self._pixmap is None or self._pixmap.size() != target.size().toSize():
                self._pixmap = QPixmap.fromImage(self._rendered).scaled(
                    target.size().toSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            painter.drawPixmap(target.topLeft(), self._pixmap)
        else:
            # Life size or larger: draw only the part on screen, with hard
            # pixel edges from 2x up so single pixels can be inspected.
            if self._full_pixmap is None:
                self._full_pixmap = QPixmap.fromImage(self._rendered)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, scale < 2.0)
            source = QRectF(
                (visible.x() - target.x()) / scale,
                (visible.y() - target.y()) / scale,
                visible.width() / scale,
                visible.height() / scale,
            )
            painter.drawPixmap(visible, self._full_pixmap, source)
        painter.restore()
        if self._zoom > 1.0 + 1e-6:
            self._paint_zoom_label(painter, scale)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(visible)

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
                painter.setPen(QPen(accent(), 1))
            painter.drawRect(rect)

        if self.doc is not None:
            self._paint_marks_overlay(painter)

        if self.tool == "text":
            self._paint_words(painter)
        elif self._pointer_on_image() and self.tool in DRAWN_CURSOR_TOOLS:
            self._paint_tool_cursor(painter, target)

    def _paint_zoom_label(self, painter: QPainter, scale: float) -> None:
        """How large the snip is shown, bottom right, while zoomed in."""
        text = f"{round(scale * 100)}%"
        metrics = painter.fontMetrics()
        box = QRectF(0, 0, metrics.horizontalAdvance(text) + 14, metrics.height() + 6)
        box.moveBottomRight(self._area().bottomRight() - QPointF(8, 8))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(16, 16, 19, 200))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor("#e6e6ec"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

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
        elif self.tool == "picker":
            painter.restore()
            self._paint_loupe(painter, target)
            return
        elif self.tool in ("crop", "redact") and self._drag_from is None:
            # Guides across the whole screenshot, for lining up the first corner.
            for pen in (QPen(QColor(0, 0, 0, 120), 1), QPen(QColor(255, 255, 255, 170), 1, Qt.PenStyle.DashLine)):
                painter.setPen(pen)
                painter.drawLine(QPointF(target.left(), pos.y()), QPointF(target.right(), pos.y()))
                painter.drawLine(QPointF(pos.x(), target.top()), QPointF(pos.x(), target.bottom()))

        # The badge, for crop and redact only: their cursor is just guide
        # lines, so the icon says which of the two is in hand. The pen,
        # highlighter and eraser show their own footprint, which is enough.
        if self.tool not in BADGED_TOOLS:
            painter.restore()
            return
        reach = max(size / 2, 4) + 8
        chip = QRectF(pos.x() + reach, pos.y() + reach, 26, 26)
        painter.setPen(QPen(accent(), 1))
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
    elif kind == "text":
        # A T inside a selection frame: read the words.
        p.drawLine(QPointF(s * 0.30, s * 0.28), QPointF(s * 0.70, s * 0.28))
        p.drawLine(QPointF(s * 0.50, s * 0.28), QPointF(s * 0.50, s * 0.74))
        dash = QPen(ink, 1.1, Qt.PenStyle.DashLine)
        p.setPen(dash)
        p.drawRoundedRect(QRectF(s * 0.10, s * 0.12, s * 0.80, s * 0.76), 2, 2)
    elif kind == "quick":
        # A redaction bar with a spark: hide what was found.
        p.drawRoundedRect(QRectF(s * 0.08, s * 0.40, s * 0.62, s * 0.30), 2, 2)
        p.setBrush(ink)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(s * 0.16, s * 0.48, s * 0.46, s * 0.14))
        spark = QPainterPath()
        spark.moveTo(s * 0.80, s * 0.06)
        spark.lineTo(s * 0.66, s * 0.30)
        spark.lineTo(s * 0.78, s * 0.30)
        spark.lineTo(s * 0.70, s * 0.52)
        spark.lineTo(s * 0.92, s * 0.22)
        spark.lineTo(s * 0.80, s * 0.22)
        spark.closeSubpath()
        p.setBrush(QColor("#ffc857"))
        p.drawPath(spark)
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

    elif kind == "redo":
        # The undo arrow, not mirrored: it turns forward.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(s * 0.22, s * 0.24, s * 0.56, s * 0.56), 30 * 16, 270 * 16)
        head = QPainterPath()
        head.moveTo(s * 0.70, s * 0.12)
        head.lineTo(s * 0.80, s * 0.36)
        head.lineTo(s * 0.56, s * 0.34)
        p.drawPath(head)
    elif kind == "select":
        arrow = QPainterPath()
        arrow.moveTo(s * 0.24, s * 0.10)
        arrow.lineTo(s * 0.24, s * 0.80)
        arrow.lineTo(s * 0.42, s * 0.62)
        arrow.lineTo(s * 0.56, s * 0.90)
        arrow.lineTo(s * 0.66, s * 0.85)
        arrow.lineTo(s * 0.52, s * 0.58)
        arrow.lineTo(s * 0.76, s * 0.58)
        arrow.closeSubpath()
        p.drawPath(arrow)
    elif kind == "arrow":
        _arrow(p, QPointF(s * 0.16, s * 0.80), QPointF(s * 0.84, s * 0.16), ink, 1.8)
        p.setPen(pen)
    elif kind == "line":
        p.drawLine(QPointF(s * 0.16, s * 0.80), QPointF(s * 0.84, s * 0.16))
    elif kind == "rect":
        p.drawRect(QRectF(s * 0.14, s * 0.22, s * 0.72, s * 0.52))
    elif kind == "ellipse":
        p.drawEllipse(QRectF(s * 0.10, s * 0.22, s * 0.80, s * 0.54))
    elif kind == "label":
        # A tag with letters on it: typed words.
        tag = QPainterPath()
        tag.moveTo(s * 0.06, s * 0.50)
        tag.lineTo(s * 0.24, s * 0.24)
        tag.lineTo(s * 0.94, s * 0.24)
        tag.lineTo(s * 0.94, s * 0.76)
        tag.lineTo(s * 0.24, s * 0.76)
        tag.closeSubpath()
        p.drawPath(tag)
        p.setFont(_font(s * 0.36))
        p.drawText(QRectF(s * 0.24, s * 0.24, s * 0.70, s * 0.52), int(Qt.AlignmentFlag.AlignCenter), "Ab")
    elif kind == "step":
        p.drawEllipse(QRectF(s * 0.16, s * 0.12, s * 0.68, s * 0.68))
        p.setFont(_font(s * 0.46))
        p.drawText(QRectF(s * 0.16, s * 0.12, s * 0.68, s * 0.68), int(Qt.AlignmentFlag.AlignCenter), "1")
    elif kind == "callout":
        p.drawRoundedRect(QRectF(s * 0.36, s * 0.10, s * 0.56, s * 0.36), 3, 3)
        _arrow(p, QPointF(s * 0.44, s * 0.46), QPointF(s * 0.12, s * 0.84), ink, 1.6)
        p.setPen(pen)
    elif kind == "spotlight":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 230, 236, 70))
        p.drawRect(QRectF(s * 0.06, s * 0.14, s * 0.88, s * 0.72))
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(s * 0.30, s * 0.36, s * 0.40, s * 0.28), 2, 2)
    elif kind == "magnify":
        p.drawEllipse(QRectF(s * 0.12, s * 0.10, s * 0.54, s * 0.54))
        p.setPen(QPen(ink, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.58, s * 0.58), QPointF(s * 0.86, s * 0.86))
        p.setPen(pen)
        p.drawLine(QPointF(s * 0.39, s * 0.26), QPointF(s * 0.39, s * 0.48))
        p.drawLine(QPointF(s * 0.28, s * 0.37), QPointF(s * 0.50, s * 0.37))
    elif kind == "picker":
        # An eyedropper.
        p.save()
        p.translate(s * 0.5, s * 0.5)
        p.rotate(45)
        p.drawRoundedRect(QRectF(-s * 0.10, -s * 0.46, s * 0.20, s * 0.22), 2, 2)
        p.drawLine(QPointF(-s * 0.18, -s * 0.22), QPointF(s * 0.18, -s * 0.22))
        body = QPainterPath()
        body.moveTo(-s * 0.07, -s * 0.22)
        body.lineTo(-s * 0.07, s * 0.26)
        body.lineTo(0, s * 0.40)
        body.lineTo(s * 0.07, s * 0.26)
        body.lineTo(s * 0.07, -s * 0.22)
        p.drawPath(body)
        p.restore()
    elif kind == "stamp":
        # A clock beside a line of text: when, and where.
        p.drawEllipse(QRectF(s * 0.06, s * 0.26, s * 0.44, s * 0.44))
        p.drawLine(QPointF(s * 0.28, s * 0.36), QPointF(s * 0.28, s * 0.48))
        p.drawLine(QPointF(s * 0.28, s * 0.48), QPointF(s * 0.37, s * 0.54))
        p.drawLine(QPointF(s * 0.60, s * 0.40), QPointF(s * 0.92, s * 0.40))
        p.drawLine(QPointF(s * 0.60, s * 0.56), QPointF(s * 0.84, s * 0.56))

    if color and kind in ("pen", *SHAPE_KINDS, "label", "step", "callout", "magnify"):
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
        p.fillRect(self.rect(), skins.color("#15151a"))
        if self.kind == "highlighter":
            # Some "text" to show it is see-through.
            p.setPen(skins.color("#5c5c66"))
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
        p.setPen(QPen(skins.color("#3a3a44"), 1))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), 5, 5)
        if self.isChecked():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        elif self.underMouse():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(accent(), 1.5))
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
        self.setStyleSheet(skins.style(POPUP_STYLE))
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
        self.setStyleSheet(skins.style(POPUP_STYLE))
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


class MarkPopup(QFrame):
    """Options for shapes, labels, steps, callouts and magnify (0.11.0).

    They share one colour, so a report's marks match. Shapes add which shape
    and the line width; the text marks the text size; magnify how much larger.
    """

    changed = Signal(dict)
    TITLES = {"shape": "Shapes", "label": "Label", "step": "Numbered steps",
              "callout": "Callout", "magnify": "Magnify"}

    def __init__(self, kind: str, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popup")
        self.setStyleSheet(skins.style(POPUP_STYLE))
        self.kind = kind
        title = QLabel(self.TITLES[kind])
        title.setObjectName("PopupTitle")
        self.value = QLabel()
        self.value.setObjectName("PopupValue")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.value)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        layout.addLayout(head)

        self.choices: dict = {}
        if kind in ("shape", "magnify"):
            row = QGridLayout()
            row.setSpacing(4)
            group = QButtonGroup(self)
            options = [(k, SHAPE_NAMES[k]) for k in SHAPE_KINDS] if kind == "shape" else [
                (f, f"{f}x") for f in MAGNIFY_FACTORS]
            columns = 2 if kind == "shape" else len(options)
            for index, (value, text) in enumerate(options):
                button = QPushButton(text)
                button.setObjectName("Mode")
                button.setCheckable(True)
                if kind == "shape":
                    button.setIcon(tool_icon(value, size=18))
                button.clicked.connect(lambda _c=False: self._emit())
                group.addButton(button)
                row.addWidget(button, index // columns, index % columns)
                self.choices[value] = button
            layout.addLayout(row)

        self.slider = None
        if kind != "magnify":
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(*(PEN_WIDTHS if kind == "shape" else TEXT_SIZES))
            self.slider.valueChanged.connect(lambda _v: self._emit())
            hint = QLabel("Line width" if kind == "shape" else "Size")
            hint.setObjectName("PopupHint")
            layout.addWidget(hint)
            layout.addWidget(self.slider)

        colours = QLabel("Colour (shared by shapes, labels, steps, callouts and magnify)")
        colours.setObjectName("PopupHint")
        colours.setWordWrap(True)
        layout.addWidget(colours)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.group = QButtonGroup(self)
        self.swatches: list[Swatch] = []
        for index, color in enumerate(PEN_COLORS):
            swatch = Swatch(color)
            swatch.clicked.connect(lambda _c=False: self._emit())
            self.group.addButton(swatch)
            self.swatches.append(swatch)
            grid.addWidget(swatch, index // PEN_COLUMNS, index % PEN_COLUMNS)
        layout.addLayout(grid)
        self.setFixedWidth(240)
        self._loading = False

    def set_prefs(self, prefs: dict) -> None:
        self._loading = True
        try:
            for swatch in self.swatches:
                swatch.setChecked(swatch.color.lower() == str(prefs["mark_color"]).lower())
            if self.kind == "shape":
                self.choices[prefs["shape_kind"]].setChecked(True)
            elif self.kind == "magnify":
                self.choices[int(prefs["magnify_factor"])].setChecked(True)
            if self.slider is not None:
                key = "shape_width" if self.kind == "shape" else "text_size"
                self.slider.setValue(int(prefs[key]))
        finally:
            self._loading = False
        self._sync_value()

    def values(self) -> dict:
        out = {}
        for swatch in self.swatches:
            if swatch.isChecked():
                out["mark_color"] = swatch.color
        for value, button in self.choices.items():
            if button.isChecked():
                out["shape_kind" if self.kind == "shape" else "magnify_factor"] = value
        if self.slider is not None:
            out["shape_width" if self.kind == "shape" else "text_size"] = self.slider.value()
        return out

    def _sync_value(self) -> None:
        if self.slider is not None:
            self.value.setText(f"{self.slider.value()} px")

    def _emit(self) -> None:
        self._sync_value()
        if not self._loading:
            self.changed.emit(self.values())


# -- the tool strip ---------------------------------------------------------------------
MENU_STYLE = """
QMenu { background: #1f1f25; color: #e6e6ec; border: 1px solid #3a3a44; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 24px; border-radius: 4px; }
QMenu::item:selected { background: #232a38; color: #ffffff; }
QMenu::item:disabled { color: #6c6c78; }
QMenu::separator { height: 1px; background: #3a3a44; margin: 4px 6px; }
QMenu::indicator { width: 12px; height: 12px; left: 6px; }
"""

STRIP_STYLE = """
QWidget#ToolStrip { background: #1a1a1f; border: 1px solid #2c2c33; border-radius: 8px; }
QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 3px; color: #e6e6ec;
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

# The tool strip, in groups: select and freehand | shapes and words |
# drawing the eye | cutting and hiding, then Quick redact, the stamp, undo, redo.
TOOL_GROUPS = (
    ("select", "pen", "highlighter", "eraser"),
    ("shape", "label", "step", "callout"),
    ("spotlight", "magnify"),
    ("crop", "redact", "text", "picker"),
)

# Name, what it does, and whether it has options, for the hover box and the
# hint beside the strip.
TOOL_INFO = {
    "select": ("Select", "Click a shape, label, step, callout, spotlight or magnifier to move it; "
               "drag its square handles to resize. Double-click words to change them; Delete removes it.", ""),
    "shape": ("Shapes", "Drag to draw an arrow, line, box or ellipse. Shift keeps it straight or square.",
              "arrow, line, box or ellipse, colour and width"),
    "label": ("Label", "Click where the words go, type, then Enter.", "colour and text size"),
    "step": ("Numbered steps", "Click to drop 1, 2, 3... in order, to show the steps of an attack.",
             "colour and size"),
    "callout": ("Callout", "Drag from what to point at to where the words go, then type: "
                "an arrow and a label in one.", "colour and text size"),
    "spotlight": ("Spotlight", "Drag over what matters; everything else is dimmed. Several "
                  "spotlights keep each area bright.", ""),
    "magnify": ("Magnify", "Drag over something small (a hash, a version); a larger copy is placed "
                "beside it. Select it to move the copy.", "how much larger, and the frame colour"),
    "picker": ("Colour picker", "Hover the snip to read any pixel's colour; click to copy its hex code.", ""),
    "pen": ("Pen", "Draw freehand lines on the snip.", "colour and width"),
    "highlighter": ("Highlighter", "A see-through marker for picking out text; what is under it stays readable.", "colour and width"),
    "eraser": ("Eraser", "Drag across a pen line, highlight or redaction to remove the whole mark.", ""),
    "crop": ("Crop", "Drag the area of the snip to keep; the rest is cut away.", ""),
    "redact": ("Redact", "Drag over passwords, hashes or client details to hide them.", "blur or black out"),
    "text": ("Text", "Read the words in the snip: click a word or drag across several, then "
             "Ctrl+C or right-click to copy them as text.", "copy all text, quick redact"),
}
HINTS = {
    None: "Left-click a tool to pick it up, right-click for its options. Changes save as you go.",
    "select": "Select: click a mark to move it, drag a handle to resize, double-click to retype, Delete to remove.",
    "shape": "Shapes: drag to draw. Shift for straight lines and squares. Right-click the tool for the shape.",
    "label": "Label: click where the words go, type, Enter. Esc drops it.",
    "step": "Steps: click to number each step, 1, 2, 3... Erase one and the next continues from the highest.",
    "callout": "Callout: drag from the thing to where the words go, type, Enter.",
    "spotlight": "Spotlight: drag over what matters; the rest is dimmed.",
    "magnify": "Magnify: drag over something small; a larger copy goes beside it.",
    "picker": "Colour picker: hover to read a colour, click to copy its hex code. Shift+click copies rgb().",
    "pen": "Pen: draw on the snip. Esc or click the pen again to put it down.",
    "highlighter": "Highlighter: drag over what matters. Esc or click it again to put it down.",
    "eraser": "Eraser: drag across a mark to remove it. Esc to put it down.",
    "crop": "Crop: drag the area to keep. Esc to put it down.",
    "redact": "Redact: drag over what to hide. Esc or click it again to put it down.",
    "text": "Text: click a word or drag across several, then Ctrl+C. Shift adds more. Right-click to copy all.",
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
    # 0.11.0: redo, and the evidence stamp button.
    redo_requested = Signal()
    stamp_requested = Signal()
    # 0.10.0: the Quick redact button, and the Text tool's right-click menu.
    quick_redact_requested = Signal()
    copy_all_text_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(skins.style(STRIP_STYLE))
        self.prefs = dict(DEFAULT_PREFS)
        self.tool: str | None = None
        self.buttons: dict[str, QToolButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(1)
        for group_index, group in enumerate(TOOL_GROUPS):
            if group_index:
                rule = QFrame()
                rule.setObjectName("StripRule")
                rule.setFixedSize(1, 22)
                layout.addSpacing(3)
                layout.addWidget(rule)
                layout.addSpacing(3)
            for kind in group:
                button = QToolButton()
                button.setCheckable(True)
                button.setIconSize(QSize(20, 20))
                button.setToolTip(tool_tooltip(kind))
                button.clicked.connect(lambda _c=False, k=kind: self._on_tool_clicked(k))
                button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda _pos, k=kind: self._on_tool_right_clicked(k)
                )
                button.installEventFilter(self)
                self.buttons[kind] = button
                layout.addWidget(button)

        self.btn_quick = QToolButton()
        self.btn_quick.setObjectName("QuickRedact")
        self.btn_quick.setIconSize(QSize(20, 20))
        self.btn_quick.setToolTip(
            "<b>Quick redact</b><br>Find emails, phone numbers, hashes, passwords, keys "
            "and tokens in the snip and black them out. You see what was found first; "
            "each one can be erased afterwards, and one undo takes them all back."
        )
        self.btn_quick.clicked.connect(self.quick_redact_requested.emit)
        layout.addWidget(self.btn_quick)

        self.btn_stamp = QToolButton()
        self.btn_stamp.setObjectName("Stamp")
        self.btn_stamp.setIconSize(QSize(20, 20))
        self.btn_stamp.setToolTip(
            "<b>Evidence stamp</b><br>Add when the snip was taken and this machine's name, "
            "bottom right. Select it to move it; erase it like any mark."
        )
        self.btn_stamp.clicked.connect(self.stamp_requested.emit)
        layout.addWidget(self.btn_stamp)

        layout.addSpacing(8)
        self.btn_undo = QToolButton()
        self.btn_undo.setObjectName("Undo")
        self.btn_undo.setIcon(tool_icon("undo"))
        self.btn_undo.setIconSize(QSize(18, 18))
        self.btn_undo.setFixedSize(30, 30)
        self.btn_undo.setToolTip("Undo the last change (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_requested.emit)
        layout.addWidget(self.btn_undo)
        layout.addSpacing(2)
        self.btn_redo = QToolButton()
        self.btn_redo.setObjectName("Undo")
        self.btn_redo.setIcon(tool_icon("redo"))
        self.btn_redo.setIconSize(QSize(18, 18))
        self.btn_redo.setFixedSize(30, 30)
        self.btn_redo.setToolTip("Redo what undo took back (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo_requested.emit)
        layout.addWidget(self.btn_redo)

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
        self.mark_popups = {kind: MarkPopup(kind) for kind in ("shape", "label", "step", "callout", "magnify")}
        for popup in self.mark_popups.values():
            popup.changed.connect(lambda changes: self._set_prefs(**changes))
        self._refresh_icons()
        self.set_undo_enabled(False)
        self.set_redo_enabled(False)

    # -- state ------------------------------------------------------------------------
    def restyle(self) -> None:
        """Re-apply the strip's and the popups' stylesheets in the current skin."""
        self.setStyleSheet(skins.style(STRIP_STYLE))
        for popup in (self.pen_popup, self.hl_popup, self.redact_popup, *self.mark_popups.values()):
            popup.setStyleSheet(skins.style(POPUP_STYLE))
        self.update()

    def set_prefs(self, prefs: dict) -> None:
        self.prefs = sanitise_prefs(prefs)
        self._refresh_icons()

    def set_undo_enabled(self, on: bool) -> None:
        on = bool(on) and getattr(self, "_available", True)
        self.btn_undo.setEnabled(on)
        _fade(self.btn_undo, not on)

    def set_redo_enabled(self, on: bool) -> None:
        on = bool(on) and getattr(self, "_available", True)
        self.btn_redo.setEnabled(on)
        _fade(self.btn_redo, not on)

    def select(self, tool: str | None) -> None:
        self.tool = tool
        for kind, button in self.buttons.items():
            button.setChecked(kind == tool)
        self.hint.setText(self._hint_for(tool))
        self.tool_changed.emit(tool)

    def set_available(self, available: bool) -> None:
        """Usable only with a snip on screen; shown greyed out before that."""
        self._available = bool(available)
        for button in [*self.buttons.values(), self.btn_quick, self.btn_stamp]:
            button.setEnabled(self._available)
            # The icons are drawn, so Qt's own disabled look barely shows;
            # fade them, so a strip that cannot be used looks it.
            _fade(button, not self._available)
        if not self._available:
            self.set_undo_enabled(False)
            self.set_redo_enabled(False)
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
        for popup in (self.pen_popup, self.hl_popup, self.redact_popup, *self.mark_popups.values()):
            popup.hide()
        self.select(None if self.tool == kind else kind)

    def _on_tool_right_clicked(self, kind: str) -> None:
        """Right-click: the tool's options, with the tool picked up."""
        if not self.buttons[kind].isEnabled():
            return
        if self.tool != kind:
            self.select(kind)
        popup = self._popup_for(kind)
        if kind == "text":
            menu = QMenu(self)
            menu.setStyleSheet(skins.style(MENU_STYLE))
            menu.addAction("Copy all text", self.copy_all_text_requested.emit)
            menu.addAction("Quick redact...", self.quick_redact_requested.emit)
            button = self.buttons[kind]
            menu.exec(button.mapToGlobal(QPoint(0, button.height() + 6)))
        elif popup is not None:
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
                "redact": self.redact_popup, **self.mark_popups}.get(kind)

    def _open(self, popup, kind: str) -> None:
        if kind == "pen":
            popup.set_values(self.prefs["pen_color"], self.prefs["pen_width"])
        elif kind == "highlighter":
            popup.set_values(self.prefs["highlighter_color"], self.prefs["highlighter_width"])
        elif kind in self.mark_popups:
            popup.set_prefs(self.prefs)
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
        self.buttons["text"].setIcon(tool_icon("text"))
        self.btn_quick.setIcon(tool_icon("quick"))
        color = self.prefs["mark_color"]
        self.buttons["select"].setIcon(tool_icon("select"))
        self.buttons["shape"].setIcon(tool_icon(self.prefs["shape_kind"], color))
        for kind in ("label", "step", "callout", "magnify"):
            self.buttons[kind].setIcon(tool_icon(kind, color))
        self.buttons["spotlight"].setIcon(tool_icon("spotlight"))
        self.buttons["picker"].setIcon(tool_icon("picker"))
        self.btn_stamp.setIcon(tool_icon("stamp"))


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
    value = str(prefs.get("mark_color", out["mark_color"])).lower()
    if value in {c.lower() for c in PEN_COLORS}:
        out["mark_color"] = value
    if prefs.get("shape_kind") in SHAPE_KINDS:
        out["shape_kind"] = prefs["shape_kind"]
    for key, (low, high) in (("shape_width", PEN_WIDTHS), ("text_size", TEXT_SIZES)):
        try:
            out[key] = min(high, max(low, int(prefs.get(key, out[key]))))
        except (TypeError, ValueError):
            pass
    try:
        factor = int(prefs.get("magnify_factor", out["magnify_factor"]))
        if factor in MAGNIFY_FACTORS:
            out["magnify_factor"] = factor
    except (TypeError, ValueError):
        pass
    # The kinds Quick redact was last told to hide (0.10.0); absent: its defaults.
    kinds = prefs.get("quick_redact")
    if isinstance(kinds, (list, tuple)):
        from ocr import KINDS

        out["quick_redact"] = sorted({str(k) for k in kinds if str(k) in KINDS})
    return out
