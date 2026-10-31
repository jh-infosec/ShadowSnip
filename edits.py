"""Keeping a snip's marks editable after you leave it (0.10.0).

While a snip is open, every mark (pen, highlighter, eraser, crop, redaction)
is a separate operation on top of the original capture (annotate.py). The
files ShadowSnip writes are flattened pictures. Before 0.10.0 the list of
operations lived only in memory, so a new snip, or moving on in the full-size
view, set the marks in stone.

Now each edited snip in a lab or in the history folder gets a sidecar in a
hidden `.edits` folder next to it:

    .edits/<snip file name>.json      the operations, in order
    .edits/<snip file name>.orig.png  the original capture, before any mark

Opening the snip again (in the full-size view, or in the preview window when
it is the one on screen) loads the original and the operations, so every mark
can be erased or undone again, redactions included.

## When the sidecar is used

Only when the snip file is still exactly what ShadowSnip last wrote: the
sidecar records the file's SHA-256. A snip edited in another program, or
replaced by hand, is opened as it is now, never silently reverted to an older
version of itself.

## Redactions and the original

Because redactions stay editable, `.orig.png` is the capture *before* any
redaction: a password you blacked out is still readable there. The snip file,
the clipboard, `latest.png`, lab.md and the exported reports never use it.
But copying or zipping a whole lab folder, hidden folders included, copies the
originals too. **Keep marks editable** in Settings switches this off: no
sidecars are written or read, and **Delete edit history** removes those
already kept. Removing a snip moves its sidecar along with it into the
`removed` folder, and history pruning deletes the sidecars of the snips it
deletes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QImage

import storage
from annotate import AnnotationDoc, Crop, Erase, Redact, Restyle, Stroke

DIR_NAME = ".edits"
# Settings' Keep marks editable. Off: nothing is written or read here.
enabled = True
VERSION = 1
# A record larger than this is not read: a stroke list is a few hundred KB at
# most, and a huge file here is not one ShadowSnip wrote.
MAX_RECORD_BYTES = 20 * 1024 * 1024


def _paths(snip: Path) -> tuple[Path, Path]:
    folder = snip.parent / DIR_NAME
    return folder / f"{snip.name}.json", folder / f"{snip.name}.orig.png"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- operations as data -------------------------------------------------------------------------
def _rect(r: QRect) -> list[int]:
    return [r.x(), r.y(), r.width(), r.height()]


def op_to_dict(op) -> dict:
    if isinstance(op, Stroke):
        return {"t": "stroke", "id": op.id, "kind": op.kind, "color": op.color,
                "width": op.width,
                "points": [[round(p.x(), 2), round(p.y(), 2)] for p in op.points]}
    if isinstance(op, Redact):
        out = {"t": "redact", "id": op.id, "rect": _rect(op.rect), "mode": op.mode}
        if op.batch:
            out["batch"] = op.batch
        return out
    if isinstance(op, Crop):
        return {"t": "crop", "id": op.id, "rect": _rect(op.rect)}
    if isinstance(op, Erase):
        return {"t": "erase", "id": op.id, "targets": sorted(op.targets)}
    if isinstance(op, Restyle):
        return {"t": "restyle", "id": op.id, "target": op.target, "mode": op.mode}
    raise TypeError(f"not an annotation operation: {op!r}")


def op_from_dict(data: dict):
    """An operation back from its record. ValueError for anything malformed."""
    if not isinstance(data, dict):
        raise ValueError("operation is not an object")
    kind = data.get("t")
    ident = int(data["id"])

    def rect(value) -> QRect:
        x, y, w, h = (int(v) for v in value)
        if w < 0 or h < 0:
            raise ValueError("negative size")
        return QRect(x, y, w, h)

    if kind == "stroke":
        if data.get("kind") not in ("pen", "highlighter"):
            raise ValueError("unknown stroke kind")
        points = [QPointF(float(x), float(y)) for x, y in data["points"]]
        if not points:
            raise ValueError("stroke without points")
        return Stroke(ident, data["kind"], str(data["color"]), float(data["width"]), points)
    if kind == "redact":
        mode = data.get("mode")
        if mode not in ("black", "blur"):
            raise ValueError("unknown redaction mode")
        return Redact(ident, rect(data["rect"]), mode, int(data.get("batch", 0) or 0))
    if kind == "crop":
        return Crop(ident, rect(data["rect"]))
    if kind == "erase":
        return Erase(ident, frozenset(int(t) for t in data["targets"]))
    if kind == "restyle":
        if data.get("mode") not in ("black", "blur"):
            raise ValueError("unknown redaction mode")
        return Restyle(ident, int(data["target"]), data["mode"])
    raise ValueError(f"unknown operation {kind!r}")


# -- saving and loading -------------------------------------------------------------------------
def save(snip: Path, doc: AnnotationDoc | None, written: bytes) -> bool:
    """Record `doc` as the editable state of `snip`, whose file now holds `written`.

    A doc with no marks needs no sidecar, so any old one is removed instead.
    Returns True when a sidecar exists afterwards. Never raises: the snip file
    is already safely written, and losing editability is not worth an error.
    """
    snip = Path(snip)
    record_path, original_path = _paths(snip)
    if not enabled:
        return False
    if doc is None or not doc.ops:
        forget(snip)
        return False
    record = {
        "version": VERSION,
        "file": snip.name,
        "file_sha256": _sha256(written),
        "next_id": doc._next,
        "ops": [op_to_dict(op) for op in doc.ops],
    }
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        _hide(record_path.parent)
        # The original never changes while a snip is open, so it is written
        # once per place, not on every edit.
        written_to = getattr(doc, "originals_written", None)
        if written_to is None:
            written_to = doc.originals_written = set()
        if str(original_path) not in written_to or not original_path.is_file():
            png = _png_bytes(doc.base)
            if png is None:
                return False
            storage.write_atomic(original_path, png)
            written_to.add(str(original_path))
        storage.write_atomic(record_path, json.dumps(record).encode("utf-8"))
        return True
    except OSError:
        return False


def load(snip: Path) -> AnnotationDoc | None:
    """The editable state of `snip`: its original with the marks, or None.

    None when there is no sidecar, it is unreadable or malformed, or the snip
    file has changed since ShadowSnip wrote it.
    """
    if not enabled:
        return None
    snip = Path(snip)
    record_path, original_path = _paths(snip)
    try:
        if not record_path.is_file() or not original_path.is_file():
            return None
        if record_path.stat().st_size > MAX_RECORD_BYTES:
            return None
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("version") != VERSION:
            return None
        if record.get("file") != snip.name:
            return None
        if record.get("file_sha256") != _sha256(snip.read_bytes()):
            return None  # changed outside ShadowSnip: open it as it is now
        ops = [op_from_dict(item) for item in record.get("ops", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not ops:
        return None
    base = QImage(str(original_path))
    if base.isNull():
        return None
    doc = AnnotationDoc(base)
    doc.ops = ops
    doc.originals_written = {str(original_path)}
    highest = max(op.id for op in ops)
    try:
        next_id = int(record.get("next_id", highest + 1))
    except (TypeError, ValueError):
        next_id = highest + 1
    doc._next = max(next_id, highest + 1)
    return doc


def forget(snip: Path) -> None:
    """Remove `snip`'s sidecar, if it has one."""
    for path in _paths(Path(snip)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def move(snip: Path, new_snip: Path) -> None:
    """`snip` was moved to `new_snip`: take its sidecar along, under the new name."""
    snip, new_snip = Path(snip), Path(new_snip)
    old_record, old_original = _paths(snip)
    if not old_record.is_file():
        forget(snip)
        return
    new_record, new_original = _paths(new_snip)
    try:
        new_record.parent.mkdir(parents=True, exist_ok=True)
        _hide(new_record.parent)
        record = json.loads(old_record.read_text(encoding="utf-8"))
        record["file"] = new_snip.name
        if old_original.is_file():
            old_original.replace(new_original)
        storage.write_atomic(new_record, json.dumps(record).encode("utf-8"))
        old_record.unlink()
    except (OSError, ValueError):
        # Better no sidecar than one left behind holding an unredacted original.
        forget(snip)


def prune(folder: Path, keep_names) -> int:
    """Delete sidecars in `folder`/.edits whose snip is not in `keep_names`."""
    edits_dir = Path(folder) / DIR_NAME
    if not edits_dir.is_dir():
        return 0
    keep = set(keep_names)
    removed = 0
    for path in edits_dir.iterdir():
        name = path.name
        for suffix in (".json", ".orig.png"):
            if name.endswith(suffix):
                if name[: -len(suffix)] not in keep:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
                break
    return removed


def delete_all(folders) -> int:
    """Remove every sidecar under each of `folders` (their `.edits`, at any depth)."""
    removed = 0
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for edits_dir in [p for p in folder.rglob(DIR_NAME) if p.is_dir()]:
            for path in edits_dir.iterdir():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
            try:
                edits_dir.rmdir()
            except OSError:
                pass
    return removed


# -- internals ----------------------------------------------------------------------------------
def _png_bytes(image: QImage) -> bytes | None:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data()) if ok else None


def _hide(folder: Path) -> None:
    """Mark the folder hidden on Windows, where a leading dot does not hide it."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x2
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(folder))
        if attrs != -1 and not attrs & FILE_ATTRIBUTE_HIDDEN:
            ctypes.windll.kernel32.SetFileAttributesW(str(folder), attrs | FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        pass
