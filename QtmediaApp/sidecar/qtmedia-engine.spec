# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

app_root = Path(SPECPATH).parent
repository_root = app_root.parent

analysis = Analysis(
    [str(app_root / "sidecar" / "entrypoint.py")],
    pathex=[
        str(app_root / "sidecar" / "src"),
        str(repository_root / "Qtmedia" / "src"),
    ],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="qtmedia-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
