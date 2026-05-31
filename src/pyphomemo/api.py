"""High-level library API for printing to a Phomemo M110 over Bluetooth LE.

These are thin async convenience wrappers over the rendering helpers in
:mod:`pyphomemo.imaging` and the BLE transport in :mod:`pyphomemo.printer`.

Example::

    import asyncio
    from pyphomemo import print_text, print_image

    asyncio.run(print_text("12:CB:A3:08:0F:34", "Box A-12", label="40x30"))
    asyncio.run(print_image("12:CB:A3:08:0F:34", "label.png", label="40x30"))
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import imaging, protocol
from .printer import PhomemoPrinter, print_raster


async def print_text(
    address: str | None,
    text: str,
    *,
    label: str = "40x30",
    width: int | None = None,
    font_size: int = 32,
    font_path: str | None = None,
    align: str = "left",
    threshold: int | None = None,
    speed: int = protocol.DEFAULT_SPEED,
    density: int = protocol.DEFAULT_DENSITY,
    media: int = protocol.DEFAULT_MEDIA,
    debug: bool = False,
) -> int:
    """Render ``text`` to a label-width bitmap and print it.

    ``label`` is a "WxH" spec in mm (width sets the print width); ``width`` (px,
    multiple of 8) overrides it. Returns the printed height in dots.
    """
    width_px = width if width is not None else imaging.label_to_px(label)[0]
    raster, height, _ = imaging.text_to_raster(
        text, width=width_px, font_size=font_size, font_path=font_path,
        align=align, threshold=threshold,
    )
    await print_raster(
        address, raster, height, width_bytes=width_px // 8,
        speed=speed, density=density, media=media, debug=debug,
    )
    return height


async def print_image(
    address: str | None,
    image: str | Path | Image.Image,
    *,
    label: str = "40x30",
    fit: bool = True,
    width: int | None = None,
    threshold: int | None = None,
    speed: int = protocol.DEFAULT_SPEED,
    density: int = protocol.DEFAULT_DENSITY,
    media: int = protocol.DEFAULT_MEDIA,
    debug: bool = False,
) -> int:
    """Render an image (path or PIL ``Image``) to the label and print it.

    With ``fit`` the image is scaled to fit the whole ``WxH`` label; otherwise it
    is scaled to the width only. ``width`` (px) overrides the label width and
    disables box-fitting. Returns the printed height in dots.
    """
    img = image if isinstance(image, Image.Image) else imaging.load_image(image)
    width_px, height_px = imaging.label_to_px(label)
    if width is not None:
        width_px = width
    box_height = height_px if (fit and width is None) else None
    raster, height, _ = imaging.image_to_raster(
        img, width=width_px, height=box_height, threshold=threshold,
    )
    await print_raster(
        address, raster, height, width_bytes=width_px // 8,
        speed=speed, density=density, media=media, debug=debug,
    )
    return height
