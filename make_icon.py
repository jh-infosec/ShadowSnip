"""Render the ShadowSnip icon to shadowsnip.ico and shadowsnip.png.

The app draws its own icon at runtime, but a PyInstaller build needs a real
.ico file on disk to embed in the .exe, and the Linux launcher entry needs a
.png. This draws the same icon with Pillow and writes both. Run it once
before building:

    python make_icon.py

Requires Pillow (already a dependency). No Qt needed.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    """The same icon app._draw_icon_pixmap draws, in Pillow terms."""
    scale = 4  # supersample, then downscale, for clean curves at small sizes
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    inset = s // 5
    radius = max(2, s // 6)

    # Rounded dark body.
    d.rounded_rectangle([2 * scale, 2 * scale, s - 2 * scale, s - 2 * scale],
                        radius=radius, fill=(24, 24, 28, 255))

    # Dashed marquee rectangle.
    marquee = (235, 235, 240, 255)
    dash = max(2, s // 20)
    gap = dash
    left, top, right, bottom = inset, inset, s - inset, s - inset
    width = max(scale, s // 40)

    def dashed_h(y):
        x = left
        while x < right:
            d.line([x, y, min(x + dash, right), y], fill=marquee, width=width)
            x += dash + gap

    def dashed_v(x):
        y = top
        while y < bottom:
            d.line([x, y, x, min(y + dash, bottom)], fill=marquee, width=width)
            y += dash + gap

    dashed_h(top)
    dashed_h(bottom)
    dashed_v(left)
    dashed_v(right)

    # Blue accent dot at the lower-right marquee corner.
    dot = s // 5
    cx, cy = right, bottom
    d.ellipse([cx - dot // 2, cy - dot // 2, cx + dot // 2, cy + dot // 2],
              fill=(10, 99, 196, 255))

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    sizes = (16, 24, 32, 48, 64, 128, 256)
    out = Path(__file__).with_name("shadowsnip.ico")
    # Draw the largest frame and let Pillow build every size from it via
    # append_images; passing a bare sizes list to a small base image only
    # emits the base, which is the trap here.
    base = draw(256)
    base.save(
        out,
        format="ICO",
        sizes=[(edge, edge) for edge in sizes],
        append_images=[draw(edge) for edge in sizes if edge != 256],
    )
    print(f"wrote {out} with sizes {', '.join(str(s) for s in sizes)}")
    png = out.with_suffix(".png")
    base.save(png, format="PNG")
    print(f"wrote {png} (256 x 256, for the Linux launcher entry)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
