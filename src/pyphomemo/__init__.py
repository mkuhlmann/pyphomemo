"""pyphomemo — print text and images on a Phomemo M110 over Bluetooth LE.

Public API
----------
High-level (connect + print in one call)::

    from pyphomemo import print_text, print_image, scan

Transport / lower level::

    from pyphomemo import PhomemoPrinter, print_raster, PrinterError

Rendering helpers (no hardware needed)::

    from pyphomemo import (
        text_to_raster, image_to_raster, text_to_image,
        label_to_px, parse_label_size, mm_to_px,
    )

Protocol/constants are available via ``pyphomemo.protocol``.
"""

from __future__ import annotations

from . import imaging, protocol
from .api import print_image, print_text
from .imaging import (
    PX_PER_MM,
    image_to_raster,
    label_to_px,
    load_font,
    load_image,
    mm_to_px,
    parse_label_size,
    text_to_image,
    text_to_raster,
)
from .printer import (
    ENV_ADDR,
    PhomemoPrinter,
    PrinterError,
    ScanResult,
    is_phomemo_name,
    print_raster,
    resolve_address,
    scan,
)
from .protocol import BYTES_PER_LINE, PRINTER_WIDTH_PX

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("pyphomemo")
except (ImportError, PackageNotFoundError):  # not installed (e.g. source tree)
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    # high-level
    "print_text",
    "print_image",
    "scan",
    # transport
    "PhomemoPrinter",
    "print_raster",
    "resolve_address",
    "PrinterError",
    "ScanResult",
    "is_phomemo_name",
    "ENV_ADDR",
    # rendering
    "text_to_raster",
    "image_to_raster",
    "text_to_image",
    "label_to_px",
    "parse_label_size",
    "mm_to_px",
    "load_image",
    "load_font",
    # constants / submodules
    "PRINTER_WIDTH_PX",
    "BYTES_PER_LINE",
    "PX_PER_MM",
    "protocol",
    "imaging",
]
