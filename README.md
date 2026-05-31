# pyphomemo

Print **text** and **images** on a **Phomemo M110** label printer over **Bluetooth LE**
— from the CLI, a small FastAPI web server with a job queue, or as a Python library.

## Install

Uses [`uv`](https://docs.astral.sh/uv/) with your activated virtualenv:

```bash
uv sync
```

## Printer address

Every command needs the printer's BLE MAC address. Supply it with `--addr` or the
`PHOMEMO_ADDR` environment variable.

```bash
phomemo scan                     # discover nearby BLE devices, find the M110
export PHOMEMO_ADDR=AA:BB:CC:DD:EE:FF
```

## CLI

```bash
# Text (defaults to a 40x30 mm label)
phomemo print-text "Hello world" --label 40x30 --font-size 40 --align center
phomemo print-text "Box A-12" --density 12

# Image — scaled to fit the whole label (Floyd–Steinberg dithering by default)
phomemo print-image logo.png --label 40x30
phomemo print-image photo.jpg --label 50x30 --threshold 128
phomemo print-image banner.png --label 40x0 --no-fit   # continuous: width only, any height

# Dry run — render to a PNG instead of printing (no hardware needed)
phomemo print-text "Preview me" --out preview.png
phomemo print-image logo.png --out preview.png
```

**Label size.** `--label/-l WxH` is in **millimetres** (default `40x30`). The M110
prints at 8 dots/mm, so `40x30` → 320×240 dots. Width is the dimension across the
print head (max 48 mm / 384 dots). Use height `0` (e.g. `40x0`) for continuous
media. For images, `--fit` (default) scales the whole image into the `WxH` label;
`--no-fit` scales to the width only and lets the height follow the aspect ratio.

Common options: `--addr/-a`, `--label/-l` (mm), `--width` (px override, multiple
of 8), `--density` (1–15), `--speed` (1–5), `--media` (0x0a label / 0x0b
continuous), `--debug` (log BLE services + send sequence).

## Web server

```bash
phomemo serve --host 0.0.0.0 --port 8000   # uses PHOMEMO_ADDR or --addr
```

Open <http://localhost:8000/> for the status page (submit text/image jobs and watch
the queue update live). API:

| Method | Path               | Body                                                                          |
| ------ | ------------------ | ----------------------------------------------------------------------------- |
| POST   | `/api/print/text`  | JSON `{text, label, font_size, align, density, speed, media}`                 |
| POST   | `/api/print/image` | multipart `file` (+ `label`, `fit`, `threshold`, `density`, `speed`, `media`) |
| GET    | `/api/jobs`        | list all jobs                                                                 |
| GET    | `/api/jobs/{id}`   | single job status                                                             |
| GET    | `/api/status`      | printer address, queue depth, active job                                      |

Jobs run one at a time through an in-memory async queue (cleared on restart).

## Library use

`pyphomemo` exposes a clean async API:

```python
import asyncio
from pyphomemo import print_text, print_image, scan, PhomemoPrinter

# One-shot helpers (connect, print, disconnect)
asyncio.run(print_text("12:CB:A3:08:0F:34", "Box A-12", label="40x30", align="center"))
asyncio.run(print_image("12:CB:A3:08:0F:34", "label.png", label="40x30"))

# Discover printers
print(asyncio.run(scan(timeout=8)))   # [(address, name), ...]

# Reuse one connection for several labels
async def batch(addr, texts):
    async with PhomemoPrinter(addr) as p:
        from pyphomemo import text_to_raster
        for t in texts:
            raster, height, _ = text_to_raster(t, width=320, align="center")
            await p.print_raster(raster, height, width_bytes=320 // 8)

asyncio.run(batch("12:CB:A3:08:0F:34", ["A-1", "A-2", "A-3"]))
```

Exported names: `print_text`, `print_image`, `scan`, `PhomemoPrinter`,
`print_raster`, `resolve_address`, `PrinterError`, `ENV_ADDR`, the rendering
helpers (`text_to_raster`, `image_to_raster`, `text_to_image`, `label_to_px`,
`parse_label_size`, `mm_to_px`, `load_image`, `load_font`), constants
(`PRINTER_WIDTH_PX`, `BYTES_PER_LINE`, `PX_PER_MM`), and the `protocol` /
`imaging` submodules. Rendering helpers need no hardware — handy for previews
and tests.

## Standalone binary

Build a single self-contained `pyphomemo` executable (no Python install needed
on the target machine) with PyInstaller:

```bash
uv sync --group build      # install PyInstaller
./build.sh                 # -> dist/pyphomemo  (~25 MB, CLI + web server)
```

The binary bundles everything (CLI, web server, Pillow, bleak) — `scp
dist/pyphomemo` to another x86-64 Linux box and run it directly. (Build on the
OS/arch you want to target; PyInstaller does not cross-compile.) Installing
`upx` on your `PATH` before building shrinks it further. Under the hood it's
driven by [`pyphomemo.spec`](pyphomemo.spec).

## How it works

The M110 print head is 384 dots (48 mm) wide. Text/images are rendered to a 1-bit
raster with Pillow, then wrapped in the M110's ESC/POS command framing
(`protocol.py`) and streamed in 128-byte GATT chunks over BLE characteristic
`0xff02` (`printer.py`). Protocol details were reverse-engineered from the
projects credited below.

## Acknowledgements

This project stands entirely on the reverse-engineering work of two excellent
open-source projects — huge thanks to their authors:

- **[phomemo-tools](https://github.com/vivier/phomemo-tools)** by **Laurent Vivier** (GPL-3.0) — a Linux/CUPS driver for Phomemo printers. Its `rastertopm110` filter is the source of the M110 ESC/POS command bytes (speed `1b 4e 0d`, density `1b 4e 04`, media `1f 11`, raster `1d 76 30 00`, footer `1f f0 …`) and the 203 dpi / 8 dots-per-mm geometry.
- **[phomymo](https://github.com/transcriptionstream/phomymo)** by **transcriptionstream** (ISC) — a browser-based Web Bluetooth label designer (<https://phomymo.affordablemagic.net>). Its `ble.js`/`printer.js` gave the BLE GATT details (service `0xff00`, write `0xff02`, notify `0xff03`), the 128-byte chunked write flow, the delay-separated `printM110` send sequence, and the dithering/raster-packing approach.

Both arrived at their knowledge by sniffing the Bluetooth traffic of the official
Phomemo Android app. `pyphomemo` simply reimplements the M110 path in Python with
a CLI, web server, and library API.

## License

[MIT](LICENSE) © Manuel Kuhlmann. `pyphomemo` is a clean-room reimplementation
that uses only the documented protocol (non-copyrightable byte sequences and BLE
characteristics) from the projects above — no source code was copied from them.

## AI Notice

This project was developed largely with the help of AI: the code, tests, and
documentation were written by [Claude](https://claude.com/claude-code)
(Anthropic's Claude Code, Opus 4.x) under human direction and review. The M110
protocol itself was not invented by the model — it was derived from the
reverse-engineered reference projects credited in [Acknowledgements](#acknowledgements).
Reasonable care has been taken to review and test the output, but please use it
at your own discretion.
