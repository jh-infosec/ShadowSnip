"""Turning a captured QImage into compressed bytes.

Screenshots are mostly flat colour, so a palette-quantised PNG is usually a
fraction of the size of the raw grab with no visible difference. The pipeline
is: optional downscale, optional quantise, then PNG. If quantising ever makes
the file bigger, the truecolour version wins.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image
from PySide6.QtGui import QImage


@dataclass
class Encoded:
    data: bytes
    ext: str
    width: int
    height: int


@dataclass
class Result:
    image: Image.Image  # processed image, after any downscale/quantise
    png: bytes  # what goes on the clipboard
    disk: Encoded  # what goes to disk (may be the same PNG)
    raw_bytes: int  # size of the uncompressed grab, for the size read-out
    source_size: tuple[int, int]


def qimage_to_pil(qimage: QImage) -> Image.Image:
    """Copy a QImage into a Pillow image without going through a file."""
    converted = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    buffer = bytes(converted.constBits())

    if stride == width * 4:
        image = Image.frombytes("RGBA", (width, height), buffer)
    else:
        # Rows are padded; strip the padding one row at a time.
        rows = [buffer[y * stride : y * stride + width * 4] for y in range(height)]
        image = Image.frombytes("RGBA", (width, height), b"".join(rows))
    return image.convert("RGB")


def process(qimage: QImage, cfg: dict) -> Result:
    source = qimage_to_pil(qimage)
    source_size = source.size
    raw_bytes = source.width * source.height * 3

    image = source
    limit = int(cfg.get("max_dimension", 0) or 0)
    if limit and max(image.size) > limit:
        ratio = limit / max(image.size)
        new_size = (
            max(1, round(image.width * ratio)),
            max(1, round(image.height * ratio)),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    level = int(cfg.get("png_compress_level", 9))
    png = _to_png(image, level)

    if cfg.get("quantize"):
        colours = int(cfg.get("quantize_colors", 256))
        try:
            reduced = image.quantize(
                colors=colours,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            )
            reduced_png = _to_png(reduced, level)
            if len(reduced_png) < len(png):
                png = reduced_png
                image = reduced
        except (ValueError, OSError):
            pass

    disk = _encode_for_disk(image, png, cfg)
    return Result(
        image=image,
        png=png,
        disk=disk,
        raw_bytes=raw_bytes,
        source_size=source_size,
    )


def _to_png(image: Image.Image, level: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True, compress_level=level)
    return buffer.getvalue()


def _encode_for_disk(image: Image.Image, png: bytes, cfg: dict) -> Encoded:
    fmt = cfg.get("disk_format", "png")
    if fmt == "png":
        return Encoded(png, "png", image.width, image.height)

    buffer = io.BytesIO()
    rgb = image.convert("RGB")
    try:
        if fmt == "webp":
            rgb.save(buffer, format="WEBP", quality=int(cfg.get("webp_quality", 90)))
            return Encoded(buffer.getvalue(), "webp", image.width, image.height)
        if fmt == "jpeg":
            rgb.save(
                buffer,
                format="JPEG",
                quality=int(cfg.get("jpeg_quality", 90)),
                subsampling=0,
                optimize=True,
            )
            return Encoded(buffer.getvalue(), "jpg", image.width, image.height)
    except (OSError, ValueError):
        pass
    return Encoded(png, "png", image.width, image.height)


def to_dib(image: Image.Image) -> bytes:
    """CF_DIB payload: a BMP with its 14-byte file header removed."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="BMP")
    return buffer.getvalue()[14:]


def human_size(count: int) -> str:
    step = 1024.0
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} GB"
