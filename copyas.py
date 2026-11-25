"""Copy as: a snip on the clipboard in the format the place you paste it wants (0.19.0).

| Format      | What goes on the clipboard                                          |
|-------------|---------------------------------------------------------------------|
| PNG         | The usual copy: PNG (plus the plain bitmap, if that is on)          |
| JPEG        | A .jpg file and its bytes: much smaller for photos and busy screens |
| WebP        | A .webp file and its bytes: smaller again, for chats and the web    |
| Data URI    | Text, `data:image/png;base64,...`, for HTML, Markdown or a CSS file |
| Markdown    | Text, `![caption](data:image/png;base64,...)`, for a .md writeup    |

JPEG and WebP go on as files as well as bytes: most programs that take a
pasted picture only read PNG or a bitmap from the clipboard, and would turn
a JPEG straight back into a big PNG. Pasted as a file (into a chat, an email,
a web upload box or a folder) it stays the small file it is.

Where those files are written is the caller's choice: a `copies` folder in
the save folder, or, for a snip from an encrypted lab, the lab's private
temp folder, wiped when the lab locks. The copies folder keeps the newest
KEEP files.
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from PIL import Image

FORMATS = (
    ("png", "PNG image"),
    ("jpeg", "JPEG image (smaller)"),
    ("webp", "WebP image (smallest)"),
    ("data_uri", "Data URI (text)"),
    ("markdown", "Markdown image (text)"),
)
LABELS = dict(FORMATS)
JPEG_QUALITY = 85
WEBP_QUALITY = 80
KEEP = 10
# Above this a data URI is still made, with a warning: few editors like a
# line that long.
LARGE_TEXT = 1_000_000


class CopyAsError(RuntimeError):
    pass


def encode(image: Image.Image, fmt: str) -> bytes:
    """The image in `fmt` ("jpeg" or "webp"); PNG for anything else."""
    out = io.BytesIO()
    if fmt == "jpeg":
        flat = image
        if image.mode not in ("RGB", "L"):
            # JPEG has no transparency: put it on white, as a freeform snip is.
            flat = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            flat.paste(rgba, mask=rgba.getchannel("A"))
        flat.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    elif fmt == "webp":
        source = image if image.mode in ("RGB", "RGBA") else image.convert("RGBA")
        source.save(out, "WEBP", quality=WEBP_QUALITY, method=4)
    else:
        image.save(out, "PNG", optimize=False)
    return out.getvalue()


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def markdown(png: bytes, caption: str = "") -> str:
    alt = (caption or "snip").replace("[", "(").replace("]", ")").replace("\n", " ").strip()
    return f"![{alt}]({data_uri(png)})"


def safe_name(name: str) -> str:
    kept = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(name or "snip"))
    return kept.strip("._")[:60] or "snip"


def write_copy(folder: Path, name: str, data: bytes, suffix: str) -> Path:
    """Write the file that goes on the clipboard, keeping the folder to KEEP files."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{safe_name(name)}.{suffix}"
    temp = target.with_name(target.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(target)
    prune(folder, spare=target)
    return target


def prune(folder: Path, keep: int = KEEP, spare: Path | None = None) -> None:
    """Keep the newest `keep` files; `spare` (the one just written) is always kept."""
    try:
        files = [p for p in Path(folder).iterdir()
                 if p.is_file() and not p.name.endswith(".tmp") and p != spare]
    except OSError:
        return
    if spare is not None:
        keep -= 1
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def put_text(text: str) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText(text)


def put_file(path: Path, data: bytes, mime: str) -> None:
    """The file (to paste as a file) and its bytes (for programs that read them)."""
    import sys

    if sys.platform == "win32":
        try:
            import win32clipboard as clip

            import clipboard

            clipboard._open_with_retry(clip)
            try:
                clip.EmptyClipboard()
                clip.SetClipboardData(clipboard.CF_HDROP, clipboard.drop_files_data([str(path)]))
                for name in (mime, "JFIF" if mime == "image/jpeg" else ""):
                    if name:
                        try:
                            clip.SetClipboardData(clip.RegisterClipboardFormat(name), data)
                        except Exception:  # noqa: BLE001 - an extra format, not essential
                            pass
            finally:
                try:
                    clip.CloseClipboard()
                except Exception:  # noqa: BLE001
                    pass
            return
        except ImportError:
            pass
    from PySide6.QtCore import QByteArray, QMimeData, QUrl
    from PySide6.QtWidgets import QApplication

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(path))])
    mime_data.setData(mime, QByteArray(data))
    QApplication.clipboard().setMimeData(mime_data)


def copy(fmt: str, image: Image.Image, *, png: bytes | None = None, folder: Path | None = None,
         name: str = "snip", caption: str = "", include_dib: bool = True) -> str:
    """Put `image` on the clipboard as `fmt`. Returns what to say about it.

    `png` is the snip's PNG when the caller already has it (the usual copy
    writes exactly those bytes); `folder` is where a JPEG or WebP file goes.
    """
    import clipboard
    import imageops

    if fmt not in LABELS:
        raise CopyAsError(f"Unknown format: {fmt}")
    if fmt == "png":
        data = png if png else encode(image, "png")
        clipboard.copy(data, image, include_dib=include_dib)
        return f"Copied as PNG ({imageops.human_size(len(data))})"
    if fmt in ("data_uri", "markdown"):
        data = png if png else encode(image, "png")
        text = data_uri(data) if fmt == "data_uri" else markdown(data, caption)
        put_text(text)
        what = "a data URI" if fmt == "data_uri" else "a Markdown image"
        note = " - long for most editors" if len(text) > LARGE_TEXT else ""
        return f"Copied as {what} ({imageops.human_size(len(text))} of text{note})"
    if folder is None:
        raise CopyAsError("There is nowhere to write the file.")
    data = encode(image, fmt)
    suffix, mime = ("jpg", "image/jpeg") if fmt == "jpeg" else ("webp", "image/webp")
    path = write_copy(folder, name or time.strftime("snip_%H-%M-%S"), data, suffix)
    put_file(path, data, mime)
    label = "JPEG" if fmt == "jpeg" else "WebP"
    return f"Copied as {label} ({imageops.human_size(len(data))}), as the file {path.name}"
