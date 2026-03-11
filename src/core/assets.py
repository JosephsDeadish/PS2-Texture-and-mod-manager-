"""Asset path resolution for PS2 Mod Manager.

Works both when running from source and when frozen by PyInstaller
(sys._MEIPASS is set in frozen executables).
"""

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Return the root directory for bundled assets."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running inside a PyInstaller bundle
        return Path(sys._MEIPASS)
    # Running from source
    return Path(__file__).parent.parent.parent


_ROOT = _bundle_root()


def asset_path(relative: str) -> str:
    """Return the absolute path to *relative* inside the assets folder."""
    return str(_ROOT / "assets" / relative)


def icon_path(size: int = 256) -> str:
    """Return the path to the PNG icon for the given *size* (16/32/48/256)."""
    return asset_path(f"icon_{size}.png")


def ico_path() -> str:
    """Return the path to the Windows .ico icon file."""
    return asset_path("icon.ico")


def svg_path() -> str:
    """Return the path to the SVG icon source."""
    return asset_path("icon.svg")
