"""Render text and images into the M110's 1bpp raster format.

Mirrors references/phomemo-tools-master/cups/filter/rastertopm110.py:
the source image is inverted (so black ink = bit 1) before being packed by
Pillow's ``"1"`` mode, which is MSB-first with 0 = black -> after inversion a
black input pixel becomes a set bit, exactly what the printer wants.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .protocol import BYTES_PER_LINE, PRINTER_WIDTH_PX

# Print resolution: 203 dpi ≈ 8 dots/mm (matches phomymo PX_PER_MM and the
# phomemo-tools 203dpi driver).
PX_PER_MM = 8


def mm_to_px(mm: float) -> int:
    """Convert millimetres to printer dots, rounded to a whole byte (8 dots)."""
    px = round(mm * PX_PER_MM)
    return ((px + 7) // 8) * 8


def parse_label_size(label: str) -> tuple[float, float]:
    """Parse a "WxH" label spec in mm, e.g. "40x30". H may be 0 for continuous."""
    parts = label.lower().replace("×", "x").split("x")
    if len(parts) != 2:
        raise ValueError(f"Bad label size {label!r}; expected e.g. 40x30 (mm).")
    try:
        w, h = float(parts[0]), float(parts[1])
    except ValueError:
        raise ValueError(f"Bad label size {label!r}; expected numbers e.g. 40x30.")
    if w <= 0:
        raise ValueError("Label width must be > 0 mm.")
    return w, h


def label_to_px(label: str) -> tuple[int, int | None]:
    """Return (width_px, height_px) for a label spec; height is None if H<=0."""
    w_mm, h_mm = parse_label_size(label)
    width_px = min(mm_to_px(w_mm), PRINTER_WIDTH_PX)
    height_px = mm_to_px(h_mm) if h_mm > 0 else None
    return width_px, height_px

# Common DejaVuSans locations; Pillow ships one with many installs too.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "DejaVuSans.ttf",  # resolvable by Pillow's font path on many systems
]


def load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font, falling back to a bundled default."""
    candidates = [font_path] if font_path else []
    candidates += _FONT_CANDIDATES
    for cand in candidates:
        if not cand:
            continue
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    # Last resort: Pillow's built-in bitmap font (ignores ``size``).
    return ImageFont.load_default()


def text_to_image(
    text: str,
    *,
    width: int = PRINTER_WIDTH_PX,
    font_size: int = 32,
    font_path: str | None = None,
    align: str = "left",
    padding: int = 8,
    line_spacing: int = 4,
) -> Image.Image:
    """Render ``text`` onto a white image ``width`` px wide, height auto-sized."""
    font = load_font(font_path, font_size)
    usable = max(1, width - 2 * padding)

    # Wrap each input line to the usable pixel width.
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))

    def text_w(s: str) -> int:
        bbox = measure.textbbox((0, 0), s, font=font)
        return bbox[2] - bbox[0]

    avg_char_w = max(1, text_w("ABCabc0123") // 10)
    wrap_cols = max(1, usable // avg_char_w)

    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        if raw == "":
            lines.append("")
            continue
        wrapped = textwrap.wrap(raw, width=wrap_cols, break_long_words=True) or [""]
        # Shrink columns if a wrapped line still overflows in pixels.
        for w in wrapped:
            while text_w(w) > usable and len(w) > 1:
                w = w[:-1]
            lines.append(w)

    # Measure line height.
    asc_bbox = measure.textbbox((0, 0), "Ag", font=font)
    line_h = (asc_bbox[3] - asc_bbox[1]) + line_spacing
    height = padding * 2 + line_h * len(lines)

    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        lw = text_w(line)
        if align == "center":
            x = (width - lw) // 2
        elif align == "right":
            x = width - padding - lw
        else:
            x = padding
        draw.text((x, y), line, fill=0, font=font)
        y += line_h
    return img


def image_to_raster(
    img: Image.Image,
    *,
    width: int = PRINTER_WIDTH_PX,
    height: int | None = None,
    threshold: int | None = None,
) -> tuple[bytes, int, Image.Image]:
    """Convert any image to packed 1bpp printer bytes.

    If ``height`` is given the image is scaled to *fit* a ``width``x``height``
    box (preserving aspect) and centred on a white label-sized canvas. Without
    it the image is scaled to ``width`` and the height follows the aspect ratio.

    Returns ``(raster_bytes, out_height, preview_image)`` where ``preview_image``
    is a ``"1"``-mode Pillow image (black = ink) for dry-run/PNG dumps.
    """
    if width % 8 != 0:
        raise ValueError("width must be a multiple of 8")
    width_bytes = width // 8

    # Flatten transparency onto white, then to grayscale.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    gray = img.convert("L")

    if height is not None:
        # Fit inside the label box, preserving aspect, centred on white.
        scale = min(width / gray.width, height / gray.height)
        new_w = max(1, round(gray.width * scale))
        new_h = max(1, round(gray.height * scale))
        resized = gray.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("L", (width, height), color=255)
        canvas.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))
        gray = canvas
    elif gray.width != width:
        # Scale to target width, preserving aspect ratio.
        new_h = max(1, round(gray.height * width / gray.width))
        gray = gray.resize((width, new_h), Image.LANCZOS)

    # Invert so dark input -> high value -> set bit after "1" conversion.
    inverted = ImageOps.invert(gray)

    if threshold is None:
        bw = inverted.convert("1")  # Floyd-Steinberg dithering
    else:
        bw = inverted.point(lambda p: 255 if p >= threshold else 0).convert("1")

    raster = bw.tobytes()  # MSB-first, width padded to byte boundary by Pillow
    out_height = bw.height
    if len(raster) != width_bytes * out_height:
        raise ValueError(
            f"unexpected raster length {len(raster)}; "
            f"expected {width_bytes * out_height} for {width}x{out_height}"
        )
    # Preview with black = ink (un-invert for human eyes).
    preview = ImageOps.invert(bw.convert("L")).convert("1")
    return raster, out_height, preview


def text_to_raster(
    text: str,
    *,
    width: int = PRINTER_WIDTH_PX,
    font_size: int = 32,
    font_path: str | None = None,
    align: str = "left",
    threshold: int | None = None,
) -> tuple[bytes, int, Image.Image]:
    img = text_to_image(
        text, width=width, font_size=font_size, font_path=font_path, align=align
    )
    return image_to_raster(img, width=width, threshold=threshold)


def load_image(path: str | Path) -> Image.Image:
    return Image.open(path)
