# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build for VibeFlow on Windows."""

import shutil
from pathlib import Path

ROOT = Path(SPECPATH)
FFMPEG = Path(shutil.which("ffmpeg")).resolve()
FFPROBE = Path(shutil.which("ffprobe")).resolve()

a = Analysis(
    [str(ROOT / "run_vibeflow.py")],
    pathex=[str(ROOT)],
    binaries=[(str(FFMPEG), "bin"), (str(FFPROBE), "bin")],
    datas=[
        (str(ROOT / "vibeflow" / "ui" / "resources"), "vibeflow/ui/resources"),
    ],
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "soundfile",
        "py7zr",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtPositioning",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "matplotlib",
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VibeFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "vibeflow" / "ui" / "resources" / "vibeflow.ico"),
)
