# -*- mode: python ; coding: utf-8 -*-
#
# PS2ModManager.spec — PyInstaller build spec for PS2 Mod Manager
#
# Usage (from project root):
#   pip install pyinstaller py7zr requests PyQt6
#   pyinstaller PS2ModManager.spec
#
# Output:
#   dist/PS2ModManager/        — one-folder distribution
#   dist/PS2ModManager.exe     — standalone executable (if onefile=True)
#
# On Windows the built .exe will have the PS2 controller icon embedded.
# On Linux/macOS the icon is set at runtime via QApplication.setWindowIcon().

import os
import sys
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Collect all PyQt6 plugin directories needed at runtime
# ---------------------------------------------------------------------------

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath('.')],
    binaries=collect_dynamic_libs("imageio_ffmpeg"),
    datas=[
        # Bundle the entire assets folder (icons, SVG)
        ('assets',     'assets'),
        # Bundle the src package
        ('src',        'src'),
        # Bundle the data directory (catalogue JSON files, PNACH DB)
        ('data',       'data'),
    ] + collect_data_files("imageio_ffmpeg"),
    hiddenimports=[
        # PyQt6 modules that may not be auto-detected
        'PyQt6.QtSvg',
        'PyQt6.QtSvgWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        # Optional 7z support
        'py7zr',
        'py7zr.helpers',
        'py7zr.py7zr',
        # Requests / urllib
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Unused large packages
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'test',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ (compressed Python archive)
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# EXE
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PS2ModManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows: embed the .ico file as the executable icon
    icon='assets/icon.ico',
    # Version info displayed in Windows Explorer Properties
    version=None,
)

# ---------------------------------------------------------------------------
# COLLECT (one-folder distribution)
# ---------------------------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PS2ModManager',
)
