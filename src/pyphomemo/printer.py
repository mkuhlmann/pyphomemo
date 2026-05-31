"""Async Bluetooth LE transport for the Phomemo M110 (via bleak).

The send sequence mirrors the proven phomymo `printM110` flow: speed, density
and media commands are written as discrete GATT writes separated by short
delays, followed by a single raster header, the bitmap in 128-byte chunks, and
the footer with the firmware's expected pauses. Merging these into one chunked
stream (no delays) causes the M110 to flash and discard the job.
"""

from __future__ import annotations

import asyncio
import os
import sys

from bleak import BleakClient, BleakScanner

from . import protocol

ENV_ADDR = "PHOMEMO_ADDR"

# Inter-command pauses (seconds), matching phomymo printer.js printM110.
DELAY_INIT = 0.03
DELAY_BEFORE_FOOTER = 0.30
DELAY_AFTER_FOOTER = 0.50


class PrinterError(RuntimeError):
    pass


def resolve_address(addr: str | None) -> str:
    """Return the BLE MAC from the argument or the PHOMEMO_ADDR env var."""
    resolved = addr or os.environ.get(ENV_ADDR)
    if not resolved:
        raise PrinterError(
            "No printer address. Pass --addr or set the "
            f"{ENV_ADDR} environment variable to the printer's BLE MAC."
        )
    return resolved


async def scan(timeout: float = 8.0) -> list[tuple[str, str]]:
    """Discover nearby BLE devices; returns (address, name) tuples."""
    devices = await BleakScanner.discover(timeout=timeout)
    return [(d.address, d.name or "(unknown)") for d in devices]


def _log(debug: bool, msg: str) -> None:
    if debug:
        print(f"[phomemo] {msg}", file=sys.stderr)


class PhomemoPrinter:
    """Connect to an M110 and run a structured print job over GATT."""

    def __init__(self, address: str | None = None, *, debug: bool = False):
        self.address = resolve_address(address)
        self._client: BleakClient | None = None
        self._char = protocol.WRITE_CHAR_UUID
        self._debug = debug
        self._notifications: list[bytes] = []

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self, timeout: float = 20.0) -> None:
        _log(self._debug, f"connecting to {self.address} ...")
        self._client = BleakClient(self.address, timeout=timeout)
        await self._client.connect()
        _log(self._debug, "connected")
        self._dump_services()
        if not self._has_char(self._char):
            found = self._discover_write_char()
            if found is None:
                raise PrinterError(
                    "No writable GATT characteristic found. Run with --debug to "
                    "inspect the printer's services."
                )
            _log(self._debug, f"write char {self._char} absent; using {found}")
            self._char = found
        await self._subscribe_notify()

    def _dump_services(self) -> None:
        if not self._debug:
            return
        assert self._client is not None
        for svc in self._client.services:
            _log(True, f"service {svc.uuid}")
            for ch in svc.characteristics:
                _log(True, f"  char {ch.uuid}  {sorted(ch.properties)}")

    def _has_char(self, uuid: str) -> bool:
        assert self._client is not None
        for svc in self._client.services:
            for ch in svc.characteristics:
                if ch.uuid.lower() == uuid.lower():
                    return True
        return False

    def _discover_write_char(self) -> str | None:
        assert self._client is not None
        # Prefer a characteristic on the ff00 service, then any writable one.
        for prefer_service in (protocol.SERVICE_UUID, None):
            for svc in self._client.services:
                if prefer_service and svc.uuid.lower() != prefer_service.lower():
                    continue
                for ch in svc.characteristics:
                    if "write-without-response" in ch.properties or "write" in ch.properties:
                        return ch.uuid
        return None

    async def _subscribe_notify(self) -> None:
        """Subscribe to the notify characteristic to capture status replies."""
        if not self._has_char(protocol.NOTIFY_CHAR_UUID):
            return

        def _on_notify(_sender, data: bytearray) -> None:
            self._notifications.append(bytes(data))
            _log(self._debug, f"notify <- {bytes(data).hex(' ')}")

        try:
            assert self._client is not None
            await self._client.start_notify(protocol.NOTIFY_CHAR_UUID, _on_notify)
        except Exception as exc:  # noqa: BLE001 - notify is best-effort
            _log(self._debug, f"notify subscribe failed: {exc}")

    def _supports_no_response(self) -> bool:
        assert self._client is not None
        for svc in self._client.services:
            for ch in svc.characteristics:
                if ch.uuid.lower() == self._char.lower():
                    return "write-without-response" in ch.properties
        return False

    async def _write(self, data: bytes) -> None:
        assert self._client is not None
        response = not self._supports_no_response()
        await self._client.write_gatt_char(self._char, data, response=response)

    async def _write_chunked(self, data: bytes) -> None:
        for chunk in protocol.chunk_payload(data):
            await self._write(chunk)
            await asyncio.sleep(protocol.CHUNK_DELAY_S)

    async def print_raster(
        self,
        raster: bytes,
        height: int,
        *,
        width_bytes: int = protocol.BYTES_PER_LINE,
        speed: int = protocol.DEFAULT_SPEED,
        density: int = protocol.DEFAULT_DENSITY,
        media: int = protocol.DEFAULT_MEDIA,
    ) -> None:
        """Run the full structured print sequence for one raster image."""
        if not self.connected:
            raise PrinterError("Not connected.")
        if len(raster) != width_bytes * height:
            raise ValueError(
                f"raster size {len(raster)} != width_bytes*height "
                f"({width_bytes}*{height}={width_bytes * height})"
            )

        _log(self._debug, f"speed={speed} density={density} media={media:#x} "
                          f"width_bytes={width_bytes} height={height}")

        await self._write(protocol.cmd_speed(speed))
        await asyncio.sleep(DELAY_INIT)
        await self._write(protocol.cmd_density(density))
        await asyncio.sleep(DELAY_INIT)
        await self._write(protocol.cmd_media(media))
        await asyncio.sleep(DELAY_INIT)

        await self._write(protocol.build_raster_header(height, width_bytes))
        await self._write_chunked(raster)

        await asyncio.sleep(DELAY_BEFORE_FOOTER)
        await self._write(protocol.build_footer())
        await asyncio.sleep(DELAY_AFTER_FOOTER)
        _log(self._debug, "print sequence sent")

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None

    async def __aenter__(self) -> "PhomemoPrinter":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()


async def print_raster(
    address: str | None,
    raster: bytes,
    height: int,
    *,
    width_bytes: int = protocol.BYTES_PER_LINE,
    speed: int = protocol.DEFAULT_SPEED,
    density: int = protocol.DEFAULT_DENSITY,
    media: int = protocol.DEFAULT_MEDIA,
    debug: bool = False,
) -> None:
    """Connect and stream a single raster print job to the printer."""
    async with PhomemoPrinter(address, debug=debug) as p:
        await p.print_raster(
            raster,
            height,
            width_bytes=width_bytes,
            speed=speed,
            density=density,
            media=media,
        )
