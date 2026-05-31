# PyInstaller spec for the `pyphomemo` CLI (full build: CLI + web server).
#
#   uv run pyinstaller pyphomemo.spec --noconfirm
#
# Output: dist/pyphomemo  (single self-contained executable)

from PyInstaller.utils.hooks import collect_all, copy_metadata

# The web server is imported lazily (by string) in cli.serve, so pull it in.
datas = [("src/pyphomemo/templates/index.html", "pyphomemo/templates")]
binaries = []
hiddenimports = ["pyphomemo.server"]

# Bundle our dist metadata so importlib.metadata (and `--version`) work frozen.
datas += copy_metadata("pyphomemo")

# bleak loads its OS Bluetooth backend dynamically; uvicorn auto-selects its
# event loop / HTTP protocol modules. Collect both fully so the binary works.
for pkg in ("bleak", "dbus_fast", "uvicorn"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# Heavy/unused modules PyInstaller may otherwise drag in.
excludes = [
    "tkinter", "_tkinter", "PIL.ImageTk", "PIL.ImageQt",
    "numpy", "scipy", "pandas", "matplotlib",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "IPython", "pytest", "setuptools", "pip", "wheel",
    "unittest", "pydoc_data", "lib2to3",
]

a = Analysis(
    ["build/pyphomemo_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pyphomemo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,  # used only if a upx binary is on PATH
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
)
