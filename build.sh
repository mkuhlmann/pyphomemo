#!/usr/bin/env bash
# Build a single-file `pyphomemo` binary (CLI + web server) with PyInstaller.
#
#   ./build.sh    ->  dist/pyphomemo
#
# Requires the build deps:  uv sync --group build
# Optional: install `upx` on PATH to shrink the binary further.
set -euo pipefail
cd "$(dirname "$0")"

echo "Building pyphomemo binary..."
uv run pyinstaller pyphomemo.spec --noconfirm --distpath dist --workpath build/pyi
echo
ls -lh dist/pyphomemo
echo "Done -> dist/pyphomemo"
