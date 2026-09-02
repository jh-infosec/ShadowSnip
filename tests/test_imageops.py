"""The compression pipeline.

The interesting behaviour is the quantise decision: palette reduction is the
one lossy step, and it must not fire on text-heavy or photographic grabs, nor
be kept when it barely wins.
"""

from __future__ import annotations

import io
import itertools
import random

import pytest
from PIL import Image
from PySide6.QtGui import QImage

import imageops

FLAT_COLOURS = [
    (20, 20, 25),
    (240, 240, 245),
    (10, 99, 196),
    (46, 204, 113),
    (200, 30, 30),
    (255, 200, 0),
    (120, 120, 130),
    (60, 180, 200),
]


def flat_pil(size=240) -> Image.Image:
    """A UI-like grab: a handful of flat colours in blocks."""
    image = Image.new("RGB", (size, size))
    step = size // 4
    for i, (x, y) in enumerate(
        itertools.product(range(0, size, step), range(0, size, step))
    ):
        image.paste(FLAT_COLOURS[i % len(FLAT_COLOURS)], (x, y, x + step, y + step))
    return image


def noisy_pil(size=200) -> Image.Image:
    """Stands in for a photograph or anti-aliased text: far too many colours."""
    rng = random.Random(1)
    image = Image.new("RGB", (size, size))
    image.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(size * size)
        ]
    )
    return image


def to_qimage(image: Image.Image) -> QImage:
    data = image.convert("RGBA").tobytes()
    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
    return qimage.copy()  # own the buffer, the bytes object is about to go


# -- human_size ------------------------------------------------------------
@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (3 * 1024**3, "3.0 GB"),
    ],
)
def test_human_size(count, expected):
    assert imageops.human_size(count) == expected


# -- the quantise guard ----------------------------------------------------
def test_flat_images_are_worth_quantising():
    assert imageops._worth_quantising(flat_pil(), {"quantize_max_source_colors": 4096})


def test_busy_images_are_not_worth_quantising():
    """Anti-aliased text and photographs blow past the colour ceiling."""
    assert not imageops._worth_quantising(
        noisy_pil(), {"quantize_max_source_colors": 4096}
    )


@pytest.mark.parametrize("ceiling", [0, -1])
def test_a_zero_ceiling_disables_the_check(ceiling):
    assert imageops._worth_quantising(
        noisy_pil(), {"quantize_max_source_colors": ceiling}
    )


@pytest.mark.parametrize(
    "given,expected", [(25, 25.0), (-5, 0.0), (200, 90.0), ("banana", 25.0), (None, 25.0)]
)
def test_clamp_percent(given, expected):
    assert imageops._clamp_percent(given) == expected


# -- process ---------------------------------------------------------------
def test_process_reports_the_source_size_and_raw_bytes(cfg):
    result = imageops.process(to_qimage(flat_pil(240)), cfg)
    assert result.source_size == (240, 240)
    assert result.raw_bytes == 240 * 240 * 3


def test_the_clipboard_bytes_are_a_valid_png(cfg):
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(result.png)).size == (240, 240)


def test_a_flat_grab_is_quantised_by_default(cfg):
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.image.mode == "P"


def test_a_busy_grab_stays_truecolour(cfg):
    """The whole point of the ceiling: code and terminal grabs keep their edges."""
    result = imageops.process(to_qimage(noisy_pil()), cfg)
    assert result.image.mode == "RGB"


def test_quantising_can_be_switched_off(cfg):
    cfg["quantize"] = False
    assert imageops.process(to_qimage(flat_pil()), cfg).image.mode == "RGB"


def test_the_palette_version_has_to_win_by_the_configured_margin(cfg):
    """At a 90% required saving nothing realistic qualifies, so RGB is kept."""
    cfg["quantize_min_saving"] = 90
    assert imageops.process(to_qimage(flat_pil()), cfg).image.mode == "RGB"


def test_quantising_never_makes_the_clipboard_bytes_larger(cfg):
    plain = dict(cfg, quantize=False)
    assert len(imageops.process(to_qimage(flat_pil()), cfg).png) <= len(
        imageops.process(to_qimage(flat_pil()), plain).png
    )


def test_pixels_survive_a_lossless_round_trip(cfg):
    cfg["quantize"] = False
    source = flat_pil(64)
    result = imageops.process(to_qimage(source), cfg)
    # tobytes() rather than getdata(): getdata() is deprecated in Pillow, and
    # the raw buffers differ if either the pixels or the mode differ, which is
    # exactly the comparison wanted here.
    assert (
        Image.open(io.BytesIO(result.png)).convert("RGB").tobytes()
        == source.tobytes()
    )


# -- downscaling -----------------------------------------------------------
def test_longest_edge_downscales_and_keeps_the_aspect_ratio(cfg):
    cfg["max_dimension"] = 100
    result = imageops.process(to_qimage(flat_pil(240).resize((240, 120))), cfg)
    assert max(result.image.size) == 100
    assert result.image.size == (100, 50)
    assert result.source_size == (240, 120)


def test_full_size_means_no_downscale(cfg):
    cfg["max_dimension"] = 0
    assert imageops.process(to_qimage(flat_pil(240)), cfg).image.size == (240, 240)


def test_smaller_than_the_limit_is_left_alone(cfg):
    cfg["max_dimension"] = 4000
    assert imageops.process(to_qimage(flat_pil(240)), cfg).image.size == (240, 240)


# -- disk encoding ---------------------------------------------------------
def test_png_on_disk_is_the_same_bytes_as_the_clipboard(cfg):
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.disk.ext == "png"
    assert result.disk.data is result.png


@pytest.mark.parametrize(
    "fmt,ext,magic",
    [("jpeg", "jpg", b"\xff\xd8\xff"), ("webp", "webp", b"RIFF")],
)
def test_lossy_disk_formats(cfg, fmt, ext, magic):
    cfg["disk_format"] = fmt
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.disk.ext == ext
    assert result.disk.data.startswith(magic)
    assert result.png[:8] == b"\x89PNG\r\n\x1a\n"  # the clipboard is always PNG


def test_an_unknown_disk_format_falls_back_to_png(cfg):
    cfg["disk_format"] = "tiff"
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.disk.ext == "png"


# -- conversion and CF_DIB -------------------------------------------------
def test_qimage_to_pil_preserves_pixels():
    source = flat_pil(32)
    # tobytes() also asserts the mode, since an RGBA result would not compare
    # equal to an RGB source even with identical colours.
    assert imageops.qimage_to_pil(to_qimage(source)).tobytes() == source.tobytes()


def test_to_dib_strips_the_bmp_file_header():
    """CF_DIB starts at the info header, not at 'BM'."""
    dib = imageops.to_dib(flat_pil(32))
    assert not dib.startswith(b"BM")
    assert int.from_bytes(dib[:4], "little") == 40  # BITMAPINFOHEADER size


def test_to_dib_accepts_a_palette_image(cfg):
    """The clipboard writer is handed result.image, which may be mode P."""
    result = imageops.process(to_qimage(flat_pil()), cfg)
    assert result.image.mode == "P"
    assert imageops.to_dib(result.image)
