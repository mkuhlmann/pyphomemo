"""Phomemo printer models and detection.

Only the **M-series** (M110/M120/M220) protocol is implemented today — its
command bytes live in :mod:`pyphomemo.protocol`. Other model families are
registered here as *unsupported* so a scan can name them correctly instead of
mis-driving them with the M110 protocol. Adding real support later means giving
a :class:`PrinterModel` its own command/send hooks and flipping ``supported``.

Detection from a BLE advertisement is best-effort:
  * an advertised name with a known **model prefix** (``M110``, ``T02`` …) is an
    exact match (supported or not);
  * a device that only advertises a bare **serial** (common on the M110, e.g.
    ``Q199E45K1234567``) or a known Phomemo **service UUID** falls back to
    :data:`DEFAULT_MODEL`;
  * anything else is not a Phomemo printer (``None``).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import protocol


@dataclass(frozen=True)
class PrinterModel:
    """A Phomemo printer model and its protocol parameters."""

    name: str
    width_px: int = protocol.PRINTER_WIDTH_PX
    # Advertised-name prefixes that uniquely identify this model.
    name_prefixes: tuple[str, ...] = ()
    # False = recognised but its protocol isn't implemented yet.
    supported: bool = True

    @property
    def width_bytes(self) -> int:
        return self.width_px // 8


# --- Registry ---------------------------------------------------------------
# Supported: the M-series share the 384-dot phomemo-tools protocol (protocol.py).
M110 = PrinterModel("M110", width_px=384, name_prefixes=("M110", "M120", "M220", "M200"))

# Recognised but not implemented yet (widths are informational until supported).
M260 = PrinterModel("M260", width_px=576, name_prefixes=("M260",), supported=False)
M02 = PrinterModel("M02", width_px=384, name_prefixes=("M02", "M04", "T02"), supported=False)
D30 = PrinterModel("D30", width_px=96, name_prefixes=("D30", "D110"), supported=False)
P12 = PrinterModel("P12", width_px=96, name_prefixes=("P12", "PM-"), supported=False)

MODELS: tuple[PrinterModel, ...] = (M110, M260, M02, D30, P12)
DEFAULT_MODEL = M110

_BY_NAME = {m.name: m for m in MODELS}


def get_model(name: str | None) -> PrinterModel | None:
    """Return a registered model by exact name (e.g. ``"M110"``), or None."""
    return _BY_NAME.get(name) if name else None


def _looks_like_serial(name: str | None) -> bool:
    """A bare alphanumeric serial like ``Q199E45K1234567`` (10–18 all-caps)."""
    n = (name or "").strip()
    return (
        10 <= len(n) <= 18
        and n.isalnum()
        and n == n.upper()
        and any(c.isdigit() for c in n)
        and any(c.isalpha() for c in n)
    )


def identify_model(name: str | None, service_uuids: object = ()) -> PrinterModel | None:
    """Best-effort :class:`PrinterModel` for a scanned device, or None.

    An exact model-prefix match wins (even for unsupported models, so they are
    named rather than mistaken for an M110). An otherwise-Phomemo-looking device
    (bare serial or known service UUID) falls back to :data:`DEFAULT_MODEL`.
    """
    n = (name or "").strip().upper()
    for model in MODELS:
        if model.name_prefixes and n.startswith(model.name_prefixes):
            return model
    advertised = {str(u).lower() for u in (service_uuids or [])}
    if (advertised & protocol.KNOWN_SERVICE_UUIDS) or _looks_like_serial(name):
        return DEFAULT_MODEL
    return None


def is_phomemo_name(name: str | None) -> bool:
    """Whether an advertised name looks like a Phomemo printer."""
    return identify_model(name) is not None
