"""Putting the snip on the Windows clipboard.

Two formats go on at once:

  PNG      registered format, the compressed bytes. Chrome, Word, Discord,
           Slack, Teams, GIMP, Paint.NET and most modern apps prefer it.
  CF_DIB   a plain uncompressed bitmap, for older apps (Paint, some Office
           dialogs) that only understand bitmaps. Optional.

PNG is registered first so apps that walk the format list in order find the
compressed one before the bitmap.
"""

from __future__ import annotations

import sys
import time

from imageops import to_dib

CF_DIB = 8


class ClipboardError(RuntimeError):
    pass


def copy(png_bytes: bytes, image, include_dib: bool = True) -> list[str]:
    """Place the snip on the clipboard. Returns the formats actually written."""
    if sys.platform == "win32":
        try:
            return _copy_win32(png_bytes, image, include_dib)
        except ImportError:
            pass
    return _copy_qt(png_bytes, image)


def _copy_win32(png_bytes: bytes, image, include_dib: bool) -> list[str]:
    import win32clipboard as clip

    written: list[str] = []
    _open_with_retry(clip)
    try:
        clip.EmptyClipboard()
        png_format = clip.RegisterClipboardFormat("PNG")
        clip.SetClipboardData(png_format, png_bytes)
        written.append("PNG")
        try:
            mime_format = clip.RegisterClipboardFormat("image/png")
            clip.SetClipboardData(mime_format, png_bytes)
            written.append("image/png")
        except Exception:  # noqa: BLE001 - non-fatal extra format
            pass
        if include_dib:
            clip.SetClipboardData(CF_DIB, to_dib(image))
            written.append("CF_DIB")
    finally:
        try:
            clip.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass
    return written


def _open_with_retry(clip, attempts: int = 10, delay: float = 0.05) -> None:
    """Another process can hold the clipboard open; wait it out briefly."""
    last = None
    for _ in range(attempts):
        try:
            clip.OpenClipboard()
            return
        except Exception as exc:  # noqa: BLE001 - pywin32 raises pywintypes.error
            last = exc
            time.sleep(delay)
    raise ClipboardError(f"could not open the clipboard: {last}")


def _copy_qt(png_bytes: bytes, image) -> list[str]:
    """Fallback when pywin32 is missing, or when running off Windows."""
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    mime = QMimeData()
    mime.setData("PNG", QByteArray(png_bytes))
    mime.setData("image/png", QByteArray(png_bytes))

    qimage = QImage()
    if qimage.loadFromData(png_bytes, "PNG"):
        mime.setImageData(qimage)

    QApplication.clipboard().setMimeData(mime)
    return ["PNG", "image/png"]


# -- files (0.14.0) -------------------------------------------------------------------------------
CF_HDROP = 15


def drop_files_data(paths) -> bytes:
    """A DROPFILES block naming `paths`: what Explorer puts on the clipboard for a copied file.

    20-byte header (offset to the names, a point, two flags with "wide" set),
    then each full path in UTF-16, each ending in a null, and one more null.
    """
    import struct

    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    names = "".join(str(path) + "\0" for path in paths) + "\0"
    return header + names.encode("utf-16-le")


def copy_files(paths) -> str:
    """Put files on the clipboard, to paste into Explorer, a chat or an email.

    Windows: the same file-drop block Explorer writes (CF_HDROP), straight
    through the Windows clipboard, so it stays there after ShadowSnip quits.
    Elsewhere, or without pywin32: Qt's file list (text/uri-list).
    Returns which way was used.
    """
    paths = [str(p) for p in paths]
    if sys.platform == "win32":
        try:
            import win32clipboard as clip

            _open_with_retry(clip)
            try:
                clip.EmptyClipboard()
                clip.SetClipboardData(CF_HDROP, drop_files_data(paths))
            finally:
                try:
                    clip.CloseClipboard()
                except Exception:  # noqa: BLE001
                    pass
            return "CF_HDROP"
        except ImportError:
            pass
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QApplication

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    QApplication.clipboard().setMimeData(mime)
    return "text/uri-list"
