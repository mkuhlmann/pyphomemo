"""Typer CLI for the Phomemo M110 printer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from . import imaging, printer, protocol

app = typer.Typer(
    add_completion=False,
    help="Print text and images on a Phomemo M110 over Bluetooth LE.",
)


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Print text and images on a Phomemo M110 over Bluetooth LE."""

ADDR_OPT = typer.Option(
    None,
    "--addr",
    "-a",
    envvar=printer.ENV_ADDR,
    help="Printer BLE MAC address (or set the PHOMEMO_ADDR env var).",
)


def _label_width(label: str) -> int:
    try:
        return imaging.label_to_px(label)[0]
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)


def _run_print(raster: bytes, height: int, width: int, addr: Optional[str], speed: int, density: int, media: int, debug: bool = False) -> None:
    try:
        asyncio.run(
            printer.print_raster(
                addr, raster, height, width_bytes=width // 8,
                speed=speed, density=density, media=media, debug=debug,
            )
        )
    except printer.PrinterError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # bleak/runtime errors
        typer.secho(f"Print failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command("print-text")
def print_text(
    text: str = typer.Argument(..., help="Text to print (use \\n for line breaks)."),
    addr: Optional[str] = ADDR_OPT,
    label: str = typer.Option("40x30", "--label", "-l", help="Label size WxH in mm, e.g. 40x30. Sets print width."),
    font_size: int = typer.Option(32, "--font-size", "-s", help="Font size in pixels."),
    width: Optional[int] = typer.Option(None, help="Override raster width in px (multiple of 8); takes precedence over --label."),
    align: str = typer.Option("left", help="left | center | right."),
    font: Optional[str] = typer.Option(None, help="Path to a TrueType font."),
    density: int = typer.Option(protocol.DEFAULT_DENSITY, min=1, max=15),
    speed: int = typer.Option(protocol.DEFAULT_SPEED, min=1, max=5),
    media: int = typer.Option(protocol.DEFAULT_MEDIA, help="Media type byte (0x0a=label, 0x0b=continuous)."),
    out: Optional[Path] = typer.Option(None, help="Dry run: write the raster preview PNG here instead of printing."),
    debug: bool = typer.Option(False, "--debug", help="Log BLE services and the send sequence to stderr."),
):
    """Render text to a bitmap and print it (or preview with --out)."""
    text = text.replace("\\n", "\n")  # let users pass literal \n on the shell
    width_px = width if width is not None else _label_width(label)
    raster, height, preview = imaging.text_to_raster(
        text, width=width_px, font_size=font_size, font_path=font, align=align
    )
    width = width_px
    if out is not None:
        preview.save(out)
        typer.echo(f"Wrote preview {out} ({width}x{height})")
        return
    _run_print(raster, height, width, addr, speed, density, media, debug)
    typer.secho(f"Printed text ({width}x{height}).", fg=typer.colors.GREEN)


@app.command("print-image")
def print_image(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Image file to print."),
    addr: Optional[str] = ADDR_OPT,
    label: str = typer.Option("40x30", "--label", "-l", help="Label size WxH in mm, e.g. 40x30. Image is scaled to fit."),
    fit: bool = typer.Option(True, "--fit/--no-fit", help="Fit image inside the full WxH label; --no-fit scales to width only."),
    width: Optional[int] = typer.Option(None, help="Override raster width in px (multiple of 8); takes precedence over --label."),
    threshold: Optional[int] = typer.Option(
        None, help="0-255 fixed threshold; omit for Floyd-Steinberg dithering."
    ),
    density: int = typer.Option(protocol.DEFAULT_DENSITY, min=1, max=15),
    speed: int = typer.Option(protocol.DEFAULT_SPEED, min=1, max=5),
    media: int = typer.Option(protocol.DEFAULT_MEDIA),
    out: Optional[Path] = typer.Option(None, help="Dry run: write the raster preview PNG here instead of printing."),
    debug: bool = typer.Option(False, "--debug", help="Log BLE services and the send sequence to stderr."),
):
    """Convert an image to 1bpp raster and print it (or preview with --out)."""
    img = imaging.load_image(path)
    width_px, height_px = imaging.label_to_px(label)
    if width is not None:
        width_px = width
    box_height = height_px if (fit and width is None) else None
    raster, height, preview = imaging.image_to_raster(
        img, width=width_px, height=box_height, threshold=threshold
    )
    width = width_px
    if out is not None:
        preview.save(out)
        typer.echo(f"Wrote preview {out} ({width}x{height})")
        return
    _run_print(raster, height, width, addr, speed, density, media, debug)
    typer.secho(f"Printed image ({width}x{height}).", fg=typer.colors.GREEN)


@app.command()
def scan(
    timeout: float = typer.Option(8.0, help="Scan duration in seconds."),
    all: bool = typer.Option(False, "--all", help="List every device, not just likely printers."),
):
    """Scan for nearby Bluetooth LE devices and flag likely Phomemo printers."""
    typer.echo(f"Scanning for {timeout:.0f}s...")
    devices = asyncio.run(printer.scan(timeout))
    if not devices:
        typer.echo("No devices found.")
        return

    printers = [d for d in devices if d.is_phomemo]
    shown = devices if (all or not printers) else printers
    for d in shown:
        rssi = f"{d.rssi:>4} dBm" if d.rssi is not None else "        "
        line = f"  {d.address}  {rssi}  {d.name}"
        if d.is_phomemo:
            typer.secho(f"{line}   ← Phomemo printer", fg=typer.colors.GREEN)
        else:
            typer.echo(line)

    if not printers:
        typer.secho(
            "No Phomemo printer detected. Make sure it's on and not connected "
            "elsewhere; pass --all to see every device.",
            fg=typer.colors.YELLOW,
        )
    elif len(printers) == 1:
        typer.echo(f"\nTip:  export PHOMEMO_ADDR={printers[0].address}")
    if printers and not all and len(shown) < len(devices):
        typer.echo(f"({len(devices) - len(shown)} other devices hidden; use --all to show them.)")


@app.command()
def serve(
    addr: Optional[str] = ADDR_OPT,
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
):
    """Start the FastAPI web server (print API + job queue + status page)."""
    import os
    import uvicorn

    if addr:
        os.environ[printer.ENV_ADDR] = addr
    # Resolve early so we fail fast with a clear message.
    printer.resolve_address(addr)
    typer.echo(f"Serving on http://{host}:{port}  (printer {os.environ[printer.ENV_ADDR]})")
    uvicorn.run("pyphomemo.server:app", host=host, port=port)


if __name__ == "__main__":
    app()
