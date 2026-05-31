"""Phomemo M110 wire protocol.

Command bytes reverse-engineered from the two reference projects:
  * references/phomemo-tools-master/cups/filter/rastertopm110.py  (command bytes)
  * references/phomymo-master/src/web/{ble,printer}.js             (BLE transport)

The printer speaks an ESC/POS-ish dialect. A print job is:

    speed   : 1b 4e 0d <speed>      (0x01 slow .. 0x05 fast)
    density : 1b 4e 04 <density>    (0x01 light .. 0x0f dark)
    media   : 1f 11 <media>         (0x0a label-with-gaps, 0x0b continuous)
    <raster blocks>                 (one or more GS v 0 blocks)
    footer  : 1f f0 05 00 1f f0 03 00

Each raster block:

    1d 76 30 00 <widthBytes LE16> <lines LE16> <raw 1bpp bitmap bytes>

The print head is 384 dots wide => 48 bytes per line, 1 bit per pixel,
MSB = leftmost pixel, bit set (1) = black.
"""

from __future__ import annotations

# --- BLE GATT identifiers (from phomymo ble.js / constants.js) ---------------
SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ff03-0000-1000-8000-00805f9b34fb"

# --- Physical characteristics ------------------------------------------------
PRINTER_WIDTH_PX = 384          # print head width in dots
BYTES_PER_LINE = PRINTER_WIDTH_PX // 8  # = 48

# --- Defaults ----------------------------------------------------------------
DEFAULT_SPEED = 0x05            # fast
DEFAULT_DENSITY = 0x0F          # darkest
MEDIA_LABEL_WITH_GAPS = 0x0A
MEDIA_CONTINUOUS = 0x0B
MEDIA_LABEL_WITH_MARKS = 0x26
DEFAULT_MEDIA = MEDIA_LABEL_WITH_GAPS

ESC = b"\x1b"
GS = b"\x1d"

# Send payload in 128-byte GATT chunks with a small delay (phomymo ble.js).
CHUNK_SIZE = 128
CHUNK_DELAY_S = 0.02


def _u16le(value: int) -> bytes:
    return value.to_bytes(2, "little")


# --- Individual commands (sent as discrete GATT writes, matching the working
#     phomymo printM110 flow) --------------------------------------------------
def cmd_speed(speed: int = DEFAULT_SPEED) -> bytes:
    return ESC + b"\x4e\x0d" + bytes([speed])


def cmd_density(density: int = DEFAULT_DENSITY) -> bytes:
    return ESC + b"\x4e\x04" + bytes([density])


def cmd_media(media: int = DEFAULT_MEDIA) -> bytes:
    return b"\x1f\x11" + bytes([media])


def build_raster_header(height: int, width_bytes: int = BYTES_PER_LINE) -> bytes:
    """Single GS v 0 raster header carrying the full 16-bit height.

    The M110 reads ``width_bytes * height`` bitmap bytes after this header.
    A single header (no block splitting) is what the proven BLE flow uses.
    """
    return GS + b"v0" + b"\x00" + _u16le(width_bytes) + _u16le(height)


def build_footer() -> bytes:
    """Finish-printing sequence."""
    return b"\x1f\xf0\x05\x00\x1f\xf0\x03\x00"


def build_print_payload(
    image_bytes: bytes,
    height: int,
    *,
    width_bytes: int = BYTES_PER_LINE,
    speed: int = DEFAULT_SPEED,
    density: int = DEFAULT_DENSITY,
    media: int = DEFAULT_MEDIA,
) -> bytes:
    """Concatenated print job (header + single raster block + footer).

    Used for offline inspection / hex dumps. The live BLE path sends the same
    bytes but as discrete, delay-separated writes (see printer.PhomemoPrinter).
    """
    if len(image_bytes) != width_bytes * height:
        raise ValueError(
            f"bitmap size {len(image_bytes)} != width_bytes*height "
            f"({width_bytes}*{height}={width_bytes * height})"
        )
    return b"".join(
        [
            cmd_speed(speed),
            cmd_density(density),
            cmd_media(media),
            build_raster_header(height, width_bytes),
            image_bytes,
            build_footer(),
        ]
    )


def chunk_payload(payload: bytes, chunk_size: int = CHUNK_SIZE):
    """Yield ``chunk_size``-byte slices for GATT writes."""
    for i in range(0, len(payload), chunk_size):
        yield payload[i : i + chunk_size]
