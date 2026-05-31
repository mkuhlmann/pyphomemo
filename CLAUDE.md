# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

`pyphomemo` prints text and images on a **Phomemo M110** label printer over
**Bluetooth LE**. Three surfaces share one core: a **CLI** (Typer), a **FastAPI
web server** (print API + in-memory job queue + status page), and a **Python
library** (`pyphomemo.__all__`).

## Setup & common commands

Uses [`uv`](https://docs.astral.sh/uv/) with the project `.venv`.

```bash
uv sync                      # runtime deps
uv sync --group build        # + PyInstaller (for building the binary)

uv run phomemo --help        # CLI entry point (script name is `phomemo`)
uv run phomemo --version

# Render without hardware (writes a preview PNG) — the fastest way to test:
uv run phomemo print-text "Hi" --label 40x30 --out /tmp/t.png
uv run phomemo print-image in.png --label 40x30 --out /tmp/i.png

uv run phomemo scan          # discover BLE devices (needs a BT adapter)
uv run phomemo serve         # web server on :8000 (needs PHOMEMO_ADDR or --addr)

./build.sh                   # -> dist/pyphomemo (single-file binary)
```

There is no test suite yet. Verify changes via the `--out` dry-run (renders to
PNG, no printer needed) and, for the server, by booting `serve` and curling
`/api/status`. Printing to real hardware needs `PHOMEMO_ADDR` (the printer's BLE
MAC) set via env or `--addr`.

## Layout

```
src/pyphomemo/
  protocol.py   M110 wire protocol: command-byte builders, GATT UUIDs, constants
  imaging.py    Pillow rendering: text/image -> 1bpp raster; mm<->px, label sizing
  printer.py    bleak BLE transport: PhomemoPrinter, scan(), structured send
  api.py        High-level async print_text() / print_image() (connect+render+print)
  cli.py        Typer commands: print-text, print-image, scan, serve, --version
  server.py     FastAPI app: endpoints, JobQueue worker, Jinja2 status page
  templates/index.html
  __init__.py   Public API re-exports + __version__ (from package metadata)
  __main__.py   `python -m pyphomemo`
build/pyphomemo_entry.py     PyInstaller entry script
pyphomemo.spec               PyInstaller build config
references/                  Reverse-engineering sources (read-only; see below)
```

Import direction is one-way: `cli`/`server`/`api` → `imaging` + `printer` →
`protocol`. Keep it that way (no cycles); `protocol` and `imaging` must stay
hardware-free so rendering works without bleak/a printer.

## M110 protocol facts (don't relearn these the hard way)

- **BLE GATT**: service `0xff00`, **write** char `0xff02` (write-without-response),
  notify `0xff03`. Send in **128-byte chunks** with a ~20 ms gap.
- **Send sequence matters**: speed → density → media are **discrete writes with
  ~30 ms gaps**, then a **single** `GS v 0` raster header with the full 16-bit
  height, then the bitmap chunks, then footer (300 ms before / 500 ms after).
  Merging everything into one uniformly-chunked stream makes the printer flash
  and discard the job. See `printer.PhomemoPrinter.print_raster`.
- **Geometry**: 203 dpi = **8 dots/mm**. Head is **384 dots = 48 mm = 48 bytes**
  wide. A 40×30 mm label is **320×240 dots**, i.e. **40 bytes/line** — NOT 48.
  Always derive `width_bytes` from the actual raster width (`width // 8`); the
  default 48 is only correct for full-width output.
- **Bitmap packing**: 1 bpp, MSB = leftmost pixel, bit set = black. Pillow `"1"`
  mode packs MSB-first with 0=black, so the source is inverted (`ImageOps.invert`)
  before `convert("1")` (matches phomemo-tools `rastertopm110`).

## Conventions

- Python ≥ 3.10, `from __future__ import annotations` in modules.
- `protocol.py` exposes pure byte-builder functions; new commands go there.
- Label size is a `"WxH"` mm string parsed by `imaging.label_to_px`; height `0`
  means continuous (no fixed label height).
- Frozen-binary awareness: anything reading bundled files must handle
  `sys._MEIPASS` (see `server._templates_dir`); new data files need a `datas`
  entry in `pyphomemo.spec`.
- Version is single-sourced in `pyproject.toml`; `__version__` reads it via
  `importlib.metadata`. The release workflow asserts the git tag matches it.

## Releasing

SemVer; tag `vMAJOR.MINOR.PATCH`. Bump `pyproject.toml`, then
`git tag vX.Y.Z && git push origin vX.Y.Z`. `.github/workflows/release.yml`
builds native binaries (Linux x86_64/arm64, Windows; macOS commented out) and
uploads them to the GitHub Release. See the README "Versioning & releases".

## references/ (read-only)

Vendored reverse-engineering sources, NOT part of the package and never imported:
`phomemo-tools` (CUPS driver, command bytes) and `phomymo` (Web Bluetooth app,
BLE transport). Consult them when extending the protocol or adding printer
models; credit them in the README Acknowledgements.
