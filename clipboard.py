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
