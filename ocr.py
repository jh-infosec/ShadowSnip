"""Reading the text in a snip, and finding what to redact in it (0.10.0).

Two jobs:

    recognise()     the words in an image and where each one is
    find_sensitive  which of those words are emails, phone numbers, IP
                    addresses, hashes, passwords, keys and tokens

Both stay on this machine. Nothing is sent anywhere.

## Engines

- **Windows**: the OCR engine built into Windows 10 and 11
  (`Windows.Media.Ocr`), reached through the `winrt` packages in
  requirements.txt. Nothing else to install; it reads in the languages of
  your Windows display language settings.
- **Tesseract**: on Linux (`sudo apt install tesseract-ocr`), and on Windows
  as a fallback when the built-in engine cannot be used and Tesseract is
  installed.

Screenshots are hard on OCR in two ways, both handled before Tesseract sees
the image: small text (it is scaled up) and light text on a dark background,
which is every terminal (it is inverted). The Windows engine copes with both.

## Coordinates

Word boxes are in the pixels of the image given, so they line up with the
marks in annotate.py, which use the same pixels.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

# Tesseract is given images at least this tall (pixels): small screenshot text
# reads far better scaled up.
TESSERACT_MIN_HEIGHT = 1600
TESSERACT_MAX_SCALE = 3.0
TESSERACT_TIMEOUT = 60
# Words Tesseract is less sure of than this (0 to 100) are dropped as noise.
# Kept low on purpose: long hashes and tokens are exactly the words OCR is
# least sure of, and a missed secret costs more than a stray box.
TESSERACT_MIN_CONFIDENCE = 0


class OcrError(RuntimeError):
    """No text could be read, with the reason and what to do about it."""


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    line: int  # words with the same number are on one line, in reading order

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


# -- which engine -----------------------------------------------------------------------------
def _tesseract_path() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            path = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
            if os.path.isfile(path):
                return path
    return None


def _windows_engine_ready() -> bool:
    if sys.platform != "win32":
        return False
    import importlib.util

    try:
        return importlib.util.find_spec("winrt.windows.media.ocr") is not None
    except (ImportError, ValueError):  # not installed, or an old Windows
        return False


def engine() -> str | None:
    """"windows", "tesseract", or None when there is no way to read text."""
    if _windows_engine_ready():
        return "windows"
    if _tesseract_path():
        return "tesseract"
    return None


def missing_engine_message() -> str:
    if sys.platform == "win32":
        return ("Reading text needs the Windows OCR packages. Install them with:  "
                "pip install -r requirements.txt  (the release .exe includes them)")
    return "Reading text needs Tesseract. Install it with:  sudo apt install tesseract-ocr"


def recognise(png: bytes) -> list[Word]:
    """The words in a PNG image, in reading order. Raises OcrError."""
    which = engine()
    if which == "windows":
        try:
            return _recognise_windows(png)
        except OcrError:
            if not _tesseract_path():
                raise
        except Exception as exc:  # noqa: BLE001 - a WinRT failure becomes a message
            if not _tesseract_path():
                raise OcrError(f"Windows could not read the text ({exc})") from exc
        which = "tesseract"
    if which == "tesseract":
        return _recognise_tesseract(png)
    raise OcrError(missing_engine_message())


# -- Windows ------------------------------------------------------------------------------------
def _recognise_windows(png: bytes) -> list[Word]:
    import asyncio
    import base64

    from PIL import Image
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.security.cryptography import CryptographicBuffer

    ocr_engine = OcrEngine.try_create_from_user_profile_languages()
    if ocr_engine is None:
        raise OcrError(
            "Windows has no OCR language installed. Add one in Settings > Time & "
            "language > Language & region (English includes it)."
        )
    with Image.open(io.BytesIO(png)) as img:
        img = img.convert("RGBA")
        scale = 1.0
        limit = int(getattr(OcrEngine, "max_image_dimension", 10000) or 10000)
        if max(img.size) > limit:
            scale = limit / max(img.size)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        width, height = img.size
        raw = img.tobytes()
    buffer = CryptographicBuffer.decode_from_base64_string(base64.b64encode(raw).decode("ascii"))
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        buffer, BitmapPixelFormat.RGBA8, width, height, BitmapAlphaMode.STRAIGHT
    )

    async def run():
        return await ocr_engine.recognize_async(bitmap)

    result = asyncio.run(run())
    words: list[Word] = []
    for line_number, line in enumerate(result.lines):
        for word in line.words:
            box = word.bounding_rect
            words.append(Word(
                str(word.text),
                int(round(box.x / scale)), int(round(box.y / scale)),
                max(1, int(round(box.width / scale))), max(1, int(round(box.height / scale))),
                line_number,
            ))
    return words


# -- Tesseract ----------------------------------------------------------------------------------
def _prepare_for_tesseract(png: bytes):
    """Greyscale, dark text on light, and big enough. Returns (PNG bytes, scale)."""
    from PIL import Image, ImageOps, ImageStat

    with Image.open(io.BytesIO(png)) as img:
        grey = img.convert("L")
    if ImageStat.Stat(grey).mean[0] < 128:
        grey = ImageOps.invert(grey)  # a terminal: light text on dark
    scale = 1.0
    if grey.height < TESSERACT_MIN_HEIGHT:
        scale = min(TESSERACT_MAX_SCALE, TESSERACT_MIN_HEIGHT / max(1, grey.height))
        grey = grey.resize((int(grey.width * scale), int(grey.height * scale)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    grey.save(out, "PNG")
    return out.getvalue(), scale


def _recognise_tesseract(png: bytes) -> list[Word]:
    exe = _tesseract_path()
    if exe is None:
        raise OcrError(missing_engine_message())
    prepared, scale = _prepare_for_tesseract(png)
    handle, path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(prepared)
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            done = subprocess.run(
                [exe, path, "stdout", "--psm", "3", "-c", "preserve_interword_spaces=1", "tsv"],
                capture_output=True, timeout=TESSERACT_TIMEOUT, **kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError("Reading the text took too long and was stopped.") from exc
        except OSError as exc:
            raise OcrError(f"Tesseract could not be started ({exc})") from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError(f"Tesseract could not read the image ({detail[-1] if detail else done.returncode})")
    return parse_tsv(done.stdout.decode("utf-8", "replace"), scale)


def parse_tsv(tsv: str, scale: float = 1.0) -> list[Word]:
    """Tesseract's TSV output as words, boxes scaled back to the original image."""
    words: list[Word] = []
    lines: dict[tuple, int] = {}
    rows = tsv.splitlines()
    if not rows:
        return words
    header = rows[0].split("\t")
    index = {name: i for i, name in enumerate(header)}
    needed = ("level", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text")
    if any(name not in index for name in needed):
        return words
    for row in rows[1:]:
        cells = row.split("\t")
        if len(cells) < len(header):
            continue
        try:
            if int(cells[index["level"]]) != 5:
                continue
            text = cells[index["text"]].strip()
            confidence = float(cells[index["conf"]])
        except ValueError:
            continue
        if not text or confidence < TESSERACT_MIN_CONFIDENCE or not any(c.isalnum() for c in text):
            continue
        try:
            x, y, w, h = (int(cells[index[k]]) for k in ("left", "top", "width", "height"))
        except ValueError:
            continue
        key = (cells[index["block_num"]], cells[index["par_num"]], cells[index["line_num"]])
        line = lines.setdefault(key, len(lines))
        words.append(Word(
            text,
            int(round(x / scale)), int(round(y / scale)),
            max(1, int(round(w / scale))), max(1, int(round(h / scale))),
            line,
        ))
    return words


# -- text from words ----------------------------------------------------------------------------
def text_of(words: list[Word]) -> str:
    """The words as text: one line per line, in reading order."""
    out: list[str] = []
    for line in _lines(words):
        out.append(" ".join(word.text for word in line))
    return "\n".join(out)


def _lines(words: list[Word]) -> list[list[Word]]:
    grouped: dict[int, list[Word]] = {}
    for word in words:
        grouped.setdefault(word.line, []).append(word)
    ordered = sorted(grouped.values(), key=lambda ws: (min(w.y for w in ws), min(w.x for w in ws)))
    return [sorted(ws, key=lambda w: w.x) for ws in ordered]


# -- finding what to redact ---------------------------------------------------------------------
# Each kind: what Quick redact calls it, whether it is ticked to start with,
# and the patterns that find it. A pattern's group 1, when it has one, is the
# part to hide ("password: hunter2" hides hunter2, not the word password).
KINDS = {
    "secret": ("Passwords, keys and tokens", True),
    "hash": ("Hashes", True),
    "email": ("Email addresses", True),
    "phone": ("Phone numbers", True),
    "ip": ("IP addresses", False),
}

_HEX = r"[0-9A-Fa-f]"
_PATTERNS: dict[str, list[re.Pattern]] = {
    "secret": [
        # A value after a word that says it is secret: password: x, pwd=x, token x
        re.compile(r"(?i)\b(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[_-]?key|"
                   r"access[_-]?key|private[_-]?key|client[_-]?secret|auth)\s*[:=]\s*"
                   r"[\"']?([^\s\"',;]{3,})"),
        # A password given on a command line: -p 'x', --password=x, -pw x, /p:x
        re.compile(r"(?:^|\s)(?:-p|-pw|--pass(?:word)?|-password|/p:)[\s=:]*"
                   r"[\"'\u2018\u2019\u201c\u201d]?([^\s\"'\u2018\u2019\u201c\u201d]{3,})"),
        # A tool reporting a working login: [+] DOMAIN\user:password (CrackMapExec,
        # NetExec), or user:password@host (Impacket).
        re.compile(r"\[\+\]\s+[^\s:]*\\[^\s:]+:([^\s()]{3,})"),
        re.compile(r"(?<![\w/])[\w.\\/-]+:([^\s@:/]{3,})@[\w.-]+\.\w+"),
        re.compile(r"\b(eyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,})"),           # JWT
        re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"),                      # AWS key id
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,})\b"),                     # GitHub token
        re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})\b"),                   # Slack token
        re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b"),                          # Google API key
        re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"),                          # API secret keys
        re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
    ],
    "hash": [
        re.compile(r"(\$(?:1|2[abxy]?|5|6|y|argon2(?:id|i|d)?|krb5(?:tgs|asrep)\$\d*|sha512)\$\S{8,})"),
        re.compile(rf"\b({_HEX}{{32}}:{_HEX}{{32}})\b"),                     # LM:NT
        re.compile(r"(\w+::[\w.-]*:[0-9A-Fa-f]{16}:[0-9A-Fa-f]{32}:[0-9A-Fa-f]{40,})"),  # NetNTLMv2
        # MD5/NT, SHA-1, SHA-224, SHA-256, SHA-384, SHA-512. A couple of
        # characters either way, because OCR now and then drops or doubles one.
        re.compile(rf"(?<![0-9A-Za-z])({_HEX}{{30,34}}|{_HEX}{{38,42}}|{_HEX}{{54,58}}|"
                   rf"{_HEX}{{62,66}}|{_HEX}{{94,98}}|{_HEX}{{126,130}})(?![0-9A-Za-z])"),
    ],
    "email": [
        re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
    ],
    "ip": [
        re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
                   r"(?:/\d{1,2}|:\d{1,5})?)(?![\d.])"),
        re.compile(r"(?<![\w:])((?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}|"
                   r"(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|"
                   r"fe80::[0-9A-Fa-f:]+)(?![\w:])"),
    ],
    "phone": [
        re.compile(r"(?<![\w.:/])(\+?\(?\d[\d ()-]{7,}\d)(?![\w.:/])"),
    ],
}


@dataclass
class Found:
    kind: str
    text: str
    boxes: list = field(default_factory=list)  # (x, y, w, h) per line it covers


def find_sensitive(words: list[Word], kinds=None) -> list[Found]:
    """What in `words` looks like something to hide, with the boxes to cover.

    A match inside one word covers only its share of that word's box (the
    value in `password=hunter2`), estimated from the character positions.
    """
    wanted = set(KINDS) if kinds is None else set(kinds)
    found: list[Found] = []
    for line in _lines(words):
        text, spans = _line_text(line)
        taken: list[tuple[int, int]] = []  # character ranges already claimed
        for kind in KINDS:  # KINDS is in priority order
            if kind not in wanted:
                continue
            for pattern in _PATTERNS[kind]:
                for match in pattern.finditer(text):
                    group = 1 if pattern.groups else 0
                    start, end = match.span(group)
                    value = match.group(group)
                    if kind == "phone" and not _is_phone(value):
                        continue
                    if kind == "ip" and ":" in value and "." not in value and not _is_ipv6(value):
                        continue
                    if kind == "hash" and not _hexish_hash(value):
                        continue
                    if any(start < b and a < end for a, b in taken):
                        continue
                    boxes = _boxes(line, spans, start, end)
                    if boxes:
                        taken.append((start, end))
                        found.append(Found(kind, value, boxes))
    return found


def _is_ipv6(value: str) -> bool:
    """An IPv6 address, not a time (12:30:45) or a port list."""
    if "::" in value:
        return True
    groups = value.split(":")
    return len(groups) >= 7 or any(c in "abcdefABCDEF" for c in value)


def _hexish_hash(value: str) -> bool:
    """A run of hex long enough to be a hash, not a long decimal number."""
    if value.startswith("$") or ":" in value:
        return True  # crypt formats, LM:NT, NetNTLMv2: matched by shape
    return any(c.isalpha() for c in value) and any(c.isdigit() for c in value)


def _is_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 9 <= len(digits) <= 15:
        return False
    # Dates and times (2026-10-31, 12:30:45) are not phone numbers.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return False
    return True


def _line_text(line: list[Word]) -> tuple[str, list[tuple[int, int]]]:
    parts, spans, pos = [], [], 0
    for word in line:
        if parts:
            parts.append(" ")
            pos += 1
        spans.append((pos, pos + len(word.text)))
        parts.append(word.text)
        pos += len(word.text)
    return "".join(parts), spans


def _boxes(line: list[Word], spans, start: int, end: int) -> list[tuple[int, int, int, int]]:
    """The box covering characters [start, end) of a line, with a little margin."""
    left = top = None
    right = bottom = None
    for word, (a, b) in zip(line, spans):
        if b <= start or a >= end:
            continue
        length = max(1, b - a)
        lo = (max(start, a) - a) / length
        hi = (min(end, b) - a) / length
        x0 = word.x + int(word.w * lo)
        x1 = word.x + int(round(word.w * hi))
        left = x0 if left is None else min(left, x0)
        right = x1 if right is None else max(right, x1)
        top = word.y if top is None else min(top, word.y)
        bottom = word.bottom if bottom is None else max(bottom, word.bottom)
    if left is None:
        return []
    pad = max(2, (bottom - top) // 6)
    return [(left - pad, top - pad, right - left + 2 * pad, bottom - top + 2 * pad)]
