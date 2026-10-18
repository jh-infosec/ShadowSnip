"""Skins: how ShadowSnip looks. Original, Steel, Split and Console.

Original is the look ShadowSnip has always had, and is what every stylesheet
in the code is written in. Steel and Split are built on top of it rather than
beside it:

- Stylesheets are recoloured. Every colour the original uses has a role
  (window, well, raised, edge, text...), and a skin gives each role its own
  colour. `style(css)` returns a stylesheet in the current skin; it returns the
  original unchanged when the skin is Original.
- A skin adds a short stylesheet of its own on top: flat buttons in its
  colours, translucent wells, underlined tabs.
- Colours painted in code rather than by stylesheet (the canvas, the selected
  row) go through `color()`, which maps them the same way.
- The window background is painted (`paint_background`): a gradient, soft
  light, a vignette and fine grain, redrawn to fit the window.

Buttons keep the original shape and size, and the font is the system font as
before; only colours, depth and the background change.

The skin is chosen in Settings and remembered in the config as `skin`.
Switching is live: `PreviewWindow.apply_skin()` re-applies every stylesheet.
"""

from __future__ import annotations

import random
import re

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QRadialGradient

ORIGINAL = "original"
NAMES = (ORIGINAL, "steel", "split", "console")
LABELS = {ORIGINAL: "Original", "steel": "Steel", "split": "Split", "console": "Console"}
DESCRIPTIONS = {
    ORIGINAL: "The classic ShadowSnip look",
    "steel": "Brushed grey gradient with a red accent",
    "split": "Two-tone diagonal, graphite and black, divided by a red seam",
    "console": "Night console: deep navy, electric blue, scanlines and a faint network",
}

RED = "#e5243b"
LAB = "#f0a020"
DANGER = "#e5484d"
TEXT = "#e8eaed"
BLUE = "#4d8dff"

# Each skin: the window colour, the accent, and how its background is painted.
_SKINS = {
    "steel": dict(
        surface="#2a2c30", accent=RED,
        bg=("vert", ["#45484e", "#2c2e33", "#1b1c1f"]),
        glows=[(0.5, -0.2, 0.8, "#ffffff", 26), (1.0, 1.0, 0.5, RED, 26)],
        seam=False,
    ),
    "split": dict(
        surface="#18181a", accent=RED,
        bg=("split", ["#2e2e33", "#1a1a1d", "#0c0c0d", "#050505"]),
        glows=[(0.62, 0.38, 0.22, RED, 30)],
        seam=True,
    ),
    # Deep navy with an electric blue accent: outlined buttons, a glowing
    # filled primary, scanlines and a sparse constellation behind everything.
    "console": dict(
        surface="#07101e", accent=BLUE, text="#d5e1f4", ink="#02060d", ghost=True,
        bg=("vert", ["#060c17", "#04080f", "#03060c"]),
        glows=[(0.85, -0.1, 0.65, BLUE, 42), (-0.1, 0.3, 0.5, BLUE, 20)],
        seam=False, scanlines=True, network=True,
    ),
}

# Every colour the original stylesheets and painting use, by role.
_ROLES = {
    "#1b1b1f": "root", "#101013": "deep", "#0c0c0f": "deep", "#15151a": "inset",
    "#1a1a20": "inset", "#1a1a1f": "inset", "#1f1f25": "inset", "#1c1c21": "inset",
    "#232329": "inset", "#2a2a31": "raised", "#34343d": "raised", "#3a3a44": "edge",
    "#2c2c33": "edge", "#26262c": "edge", "#e6e6ec": "text", "#d6d6de": "text",
    "#c9d6ea": "text", "#9a9aa6": "dim", "#7c7c88": "dim", "#8e8e9a": "dim",
    "#6c6c78": "faint", "#5f5f6b": "faint", "#5c5c66": "faint", "#0a63c4": "accent",
    "#1273da": "accent", "#2f8cff": "accent", "#232a38": "accentbg",
}

_current = ORIGINAL


# -- choosing ---------------------------------------------------------------------------------
def normalise(name) -> str:
    name = str(name or "").strip().lower()
    return name if name in NAMES else ORIGINAL


def set_current(name) -> str:
    global _current
    _current = normalise(name)
    return _current


def current() -> str:
    return _current


def is_original() -> bool:
    return _current == ORIGINAL


def next_name(name) -> str:
    """The skin after `name`, wrapping round: for cycling through them."""
    index = NAMES.index(normalise(name))
    return NAMES[(index + 1) % len(NAMES)]


# -- colour arithmetic --------------------------------------------------------------------------
def _rgb(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _hex(t) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in t)


def mix(a: str, b: str, t: float) -> str:
    return _hex(x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b)))


def shade(c: str, t: float) -> str:
    """Lighter for t > 0, darker for t < 0."""
    return mix(c, "#ffffff" if t > 0 else "#000000", abs(t))


def rgba(c: str, alpha: int) -> str:
    r, g, b = _rgb(c)
    return f"rgba({r},{g},{b},{alpha})"


def _ink(c: str) -> str:
    r, g, b = _rgb(c)
    return "#08080a" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


def _palette(name: str) -> dict:
    s = _SKINS[name]
    surf, accent = s["surface"], s["accent"]
    text = s.get("text", TEXT)
    inset = shade(surf, -0.32)
    return {
        "surface": surf, "accent": accent, "inset": inset, "raised": shade(surf, 0.07),
        "edge": mix(surf, accent, 0.30) if s.get("ghost") else mix(surf, text, 0.16),
        "dim": mix(text, surf, 0.42), "faint": mix(text, surf, 0.62),
        # by role, for recolouring
        "root": surf, "deep": shade(surf, -0.45), "text": text, "accentbg": mix(accent, surf, 0.82),
    }


# -- applying -----------------------------------------------------------------------------------
def color(value: str) -> QColor:
    """A colour from the original look, in the current skin."""
    if is_original():
        return QColor(value)
    role = _ROLES.get(value.lower())
    if role is None:
        return QColor(value)
    p = _palette(_current)
    return QColor(p["edge"] if role == "edge" else p[role])


def accent() -> str:
    return "#2f8cff" if is_original() else _SKINS[_current]["accent"]


def recolor(css: str) -> str:
    if is_original():
        return css
    p = _palette(_current)
    def swap(match):
        role = _ROLES.get(match.group(0).lower())
        return p[role] if role else match.group(0)
    return re.sub(r"#[0-9a-fA-F]{6}\b", swap, css)


def style(css: str) -> str:
    """A stylesheet in the current skin: recoloured, with the skin's own rules on top."""
    if is_original():
        return css
    return recolor(css) + _extra_css()


def _extra_css() -> str:
    p = _palette(_current)
    a, surf, inset, raised, edge = p["accent"], p["surface"], p["inset"], p["raised"], p["edge"]
    dim, faint, TEXT = p["dim"], p["faint"], p["text"]
    s = _SKINS[_current]
    ink = s.get("ink") or _ink(a)
    hair, hair_strong = "rgba(255,255,255,18)", "rgba(255,255,255,30)"
    if s.get("ghost"):
        hair, hair_strong = rgba(a, 40), rgba(a, 107)
    return _base_css(p, a, surf, inset, raised, edge, dim, faint, TEXT, ink, hair, hair_strong) + (
        _ghost_css(a, surf, TEXT, hair, hair_strong) if s.get("ghost") else "")


def _ghost_css(a, surf, text, hair, hair_strong) -> str:
    """Outlined buttons in the accent, as on a terminal-style site; the primary stays filled."""
    hi = mix(a, "#ffffff", 0.45)
    return f"""
QPushButton {{ background: transparent; color: {hi}; border: 1px solid {hair_strong}; }}
QPushButton:hover {{ background: {rgba(a, 26)}; border-color: {a}; }}
QPushButton:pressed {{ background: {rgba(a, 46)}; }}
QPushButton#Settings {{ background: transparent; color: {hi}; border-color: {hair_strong}; }}
QPushButton#Settings:hover {{ background: {rgba(a, 26)}; border-color: {a}; }}
QPushButton#Primary {{ background: {a}; border-color: {a}; }}
QPushButton#Primary:hover {{ background: {hi}; border-color: {hi}; }}
QPushButton:checked {{ background: {rgba(a, 40)}; border-color: {a}; color: #ffffff; }}
QLabel#Brand {{ color: {text}; font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace; }}
QTreeWidget, QTextBrowser {{ background: {rgba(shade(surf, -0.3), 165)}; border: 1px solid {hair_strong}; }}
QLineEdit, QPlainTextEdit, QComboBox {{ background: {rgba(shade(surf, -0.3), 175)}; border: 1px solid {hair_strong}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {a}; }}
QWidget#ToolStrip {{ background: {rgba(surf, 170)}; border: 1px solid {hair}; }}
"""


def _base_css(p, a, surf, inset, raised, edge, dim, faint, TEXT, ink, hair, hair_strong) -> str:
    return f"""
QWidget#Root {{ background: transparent; }}
QPushButton {{ background: {raised}; color: {TEXT}; border: 1px solid {edge}; border-radius: 4px; padding: 6px 14px; }}
QPushButton:hover {{ background: {shade(raised, 0.06)}; }}
QPushButton:pressed {{ background: {shade(raised, -0.06)}; }}
QPushButton:disabled {{ color: {faint}; }}
QPushButton#Primary {{ background: {a}; border-color: {a}; color: {ink}; }}
QPushButton#Primary:hover {{ background: {shade(a, 0.1)}; }}
QPushButton#Primary:pressed {{ background: {shade(a, -0.1)}; }}
QPushButton:checked {{ background: {mix(a, surf, 0.80)}; border-color: {mix(a, surf, 0.35)}; color: {shade(a, 0.25)}; }}
QPushButton[labActive="true"] {{ background: {mix(LAB, surf, 0.80)}; border-color: {mix(LAB, surf, 0.35)}; color: {shade(LAB, 0.15)}; }}
QPushButton#Danger {{ background: {mix(DANGER, surf, 0.84)}; border-color: {mix(DANGER, surf, 0.5)}; color: {shade(DANGER, 0.2)}; }}
QPushButton#Danger:hover {{ background: {mix(DANGER, surf, 0.76)}; }}
QPushButton#Settings {{ background: {raised}; border-color: {edge}; color: {TEXT}; }}
QPushButton#Settings:hover {{ background: {shade(raised, 0.06)}; }}
QLineEdit, QPlainTextEdit, QComboBox {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {rgba(shade(inset, -0.06), 225)}, stop:1 {rgba(inset, 200)});
    border: 1px solid {hair_strong}; border-radius: 6px; color: {TEXT}; padding: 6px 9px;
    selection-background-color: {rgba(a, 90)};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {a}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QTreeWidget, QTextBrowser {{
    background: {rgba(inset, 215)}; alternate-background-color: {shade(inset, 0.025)};
    border: 1px solid {hair}; border-radius: 6px; color: {TEXT};
}}
QTreeWidget::item:selected {{ color: {TEXT}; }}
QHeaderView::section {{
    background: {inset}; color: {dim}; border: 0; border-bottom: 1px solid {hair_strong}; padding: 5px 9px;
}}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{
    background: transparent; color: {dim}; border: 0; border-bottom: 2px solid transparent;
    padding: 6px 14px; margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {a}; }}
QWidget#ToolStrip {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {rgba(shade(surf, 0.05), 210)}, stop:1 {rgba(surf, 190)});
    border: 1px solid {hair}; border-radius: 8px;
}}
QToolButton {{ color: {TEXT}; border-radius: 6px; border: 1px solid transparent; }}
QToolButton:hover {{ background: {hair}; }}
QToolButton:checked {{ background: {rgba(a, 34)}; border: 1px solid {rgba(a, 150)}; }}
QLabel#StripHint {{ color: {dim}; }}
QLabel#SnipThumb {{ background: {shade(inset, -0.2)}; border: 1px solid {hair}; border-radius: 6px; }}
QSplitter::handle {{ background: transparent; width: 6px; }}
QLabel#Status, QLabel#FieldLabel, QLabel#SnipWhere {{ color: {dim}; }}
QLabel#Version {{ color: {faint}; }}
QLabel#Brand {{ color: {TEXT}; font-size: 14px; font-weight: 600; padding-right: 10px; }}
"""


# -- the painted background ----------------------------------------------------------------------
_GRAIN: QImage | None = None


def _grain() -> QImage:
    """A small tile of fine light and dark specks, drawn once and repeated."""
    global _GRAIN
    if _GRAIN is None:
        tile = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        tile.fill(0)
        p = QPainter(tile)
        rnd = random.Random(3)
        for _ in range(128 * 128 // 55):
            c = QColor("#ffffff" if rnd.random() < 0.5 else "#000000")
            c.setAlpha(rnd.randint(3, 7))
            p.setPen(c)
            p.drawPoint(rnd.randrange(128), rnd.randrange(128))
        p.end()
        _GRAIN = tile
    return _GRAIN


def _qc(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


def has_background() -> bool:
    return not is_original()


def paint_background(width: int, height: int) -> QImage | None:
    """The window background for the current skin, at this size. None for Original."""
    if is_original() or width <= 0 or height <= 0:
        return None
    s = _SKINS[_current]
    w, h = width, height
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    kind, stops = s["bg"]
    if kind == "vert":
        g = QLinearGradient(0, 0, 0, h)
    elif kind == "split":
        g = QLinearGradient(0, 0, w, h * 0.9)
    else:
        g = QLinearGradient(0, 0, w, h)
    n = len(stops) - 1
    for i, c in enumerate(stops):
        pos = [0.0, 0.47, 0.53, 1.0][i] if kind == "split" else i / n
        g.setColorAt(pos, _qc(c))
    p.fillRect(0, 0, w, h, g)
    for x, y, r, col, a in s["glows"]:
        rg = QRadialGradient(QPointF(x * w, y * h), r * max(w, h))
        rg.setColorAt(0, _qc(col, a))
        rg.setColorAt(0.45, _qc(col, a // 3))
        rg.setColorAt(1, _qc(col, 0))
        p.fillRect(0, 0, w, h, rg)
    if s.get("scanlines"):
        _scanlines(p, w, h, s["accent"])
    if s.get("network"):
        _network(p, w, h, s["accent"])
    if s["seam"]:
        seam = QLinearGradient(0, 0, w, h * 0.9)
        for pos, a in ((0.0, 0), (0.495, 0), (0.5, 55), (0.505, 0), (1.0, 0)):
            seam.setColorAt(pos, _qc(s["accent"], a))
        p.fillRect(0, 0, w, h, seam)
    sheen = QLinearGradient(0, 0, 0, h * 0.25)
    sheen.setColorAt(0, _qc("#ffffff", 10))
    sheen.setColorAt(1, _qc("#ffffff", 0))
    p.fillRect(0, 0, w, h, sheen)
    vignette = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.78)
    vignette.setColorAt(0.6, _qc("#000000", 0))
    vignette.setColorAt(1, _qc("#000000", 120))
    p.fillRect(0, 0, w, h, vignette)
    p.drawTiledPixmap(0, 0, w, h, _pixmap(_grain()))
    p.end()
    return img


def _scanlines(p: QPainter, w: int, h: int, colour: str) -> None:
    """One faint line every four pixels, like an old terminal."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(_qc(colour, 9))
    for y in range(0, h, 4):
        p.drawLine(0, y, w, y)
    p.restore()


def _network(p: QPainter, w: int, h: int, colour: str) -> None:
    """A sparse constellation: faint points joined to their near neighbours."""
    rnd = random.Random(11)
    count = max(12, int(w * h / 26000))
    pts = [QPointF(rnd.random() * w, rnd.random() * h) for _ in range(count)]
    reach = 0.16 * max(w, h)
    p.save()
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            d = ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
            if d < reach:
                p.setPen(QPen(_qc(colour, int(52 * (1 - d / reach))), 1))
                p.drawLine(a, b)
    p.setPen(Qt.PenStyle.NoPen)
    for a in pts:
        p.setBrush(_qc(colour, rnd.randint(40, 110)))
        r = rnd.choice((1.0, 1.2, 1.6))
        p.drawEllipse(a, r, r)
    p.restore()


def _pixmap(image: QImage):
    from PySide6.QtGui import QPixmap
    return QPixmap.fromImage(image)
