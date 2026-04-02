"""Game library scanner — discovers PS2 ROM/ISO/CHD files on disk.

Scans a user-configured folder for PS2 disc image files and attempts to
detect the game serial embedded in each filename.  The result is used
throughout the application to:

* Filter the mod browser to show only mods compatible with owned games.
* Auto-suggest a game serial when importing a mod.
* Display a summary of the user's game collection.

Supported file extensions::

    .iso   — raw ISO 9660 disc image (most common)
    .chd   — Compressed Hunks of Data (MAME/PCSX2 format)
    .bin   — raw binary disc image (often paired with .cue)
    .img   — raw disc image
    .mdf   — Media Disc Image (paired with .mds)
    .nrg   — Nero Burning ROM image
    .cso   — Compressed ISO (PSP-style; sometimes used for PS2)
    .gz    — gzip-compressed ISO

Public API::

    from src.core.game_library import scan_library, GameEntry

    games = scan_library("/path/to/roms")
    for g in games:
        print(g.serial, g.title, g.path)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from src.core.game_registry import detect_game_serial, serial_to_display

log = logging.getLogger(__name__)

# Lazy-loaded serial database singleton used to resolve CRCs for each
# detected game serial.  Imported here to avoid a circular import at module
# level (game_registry ← game_library ← serial_validator is safe because
# serial_validator does *not* import game_library).
_sdb = None


def _get_sdb():
    global _sdb
    if _sdb is None:
        from src.core.serial_validator import SerialDatabase
        _sdb = SerialDatabase()
    return _sdb

# ---------------------------------------------------------------------------
# Supported disc-image extensions (lower-case, with leading dot)
# ---------------------------------------------------------------------------

GAME_EXTENSIONS: frozenset = frozenset({
    ".iso",
    ".chd",
    ".bin",
    ".img",
    ".mdf",
    ".nrg",
    ".cso",
    ".gz",
})


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class GameEntry:
    """A single discovered PS2 disc image file."""

    #: Absolute path to the file.
    path: str

    #: Filename without parent directory (convenience attribute).
    filename: str

    #: Detected PS2 serial (e.g. ``"SLUS-20062"``), or empty string if unknown.
    serial: str

    #: Human-readable title from the local registry, or empty string if unknown.
    title: str

    #: File size in bytes.
    size_bytes: int = 0

    #: Known CRCs for this game, looked up from the serial database.
    #: An empty list means the serial was not found in the DB or no CRCs
    #: are recorded for this game.
    crcs: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Return a UI-friendly label: ``"Title (SERIAL)"`` or just the filename."""
        if self.title and self.serial:
            return f"{self.title}  ({self.serial})"
        if self.serial:
            return f"{self.serial}  —  {self.filename}"
        return self.filename

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lower()

    @property
    def disc_type(self) -> str:
        """Return the disc image format as an upper-case string.

        Common values: ``"ISO"``, ``"CHD"``, ``"BIN"``, ``"IMG"``, ``"MDF"``,
        ``"NRG"``, ``"CSO"``, ``"GZ"``.  Falls back to the extension without
        the leading dot (upper-cased) for any other extension.

        Examples::

            GameEntry(path="/roms/game.iso", ...).disc_type  # "ISO"
            GameEntry(path="/roms/game.chd", ...).disc_type  # "CHD"
        """
        _EXT_MAP = {
            ".iso": "ISO", ".chd": "CHD", ".bin": "BIN",
            ".img": "IMG", ".mdf": "MDF", ".nrg": "NRG",
            ".cso": "CSO", ".gz":  "GZ",
        }
        ext = self.extension
        return _EXT_MAP.get(ext, ext.lstrip(".").upper() or "Unknown")

    @property
    def region(self) -> str:
        """Return the region derived from the detected serial prefix.

        Returns one of ``"NTSC-U"``, ``"PAL"``, ``"NTSC-J"``, ``"NTSC-K"``,
        ``"Asia"``, or an empty string when the serial is missing/unknown.

        Examples::

            GameEntry(serial="SLUS-20062", ...).region  # "NTSC-U"
            GameEntry(serial="SLES-50000", ...).region  # "PAL"
            GameEntry(serial="SLPS-25000", ...).region  # "NTSC-J"
        """
        from src.core.game_registry import serial_to_region
        return serial_to_region(self.serial)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_library(
    directory: str,
    *,
    recursive: bool = False,
) -> List[GameEntry]:
    """Scan *directory* for PS2 disc image files and return a list of
    :class:`GameEntry` objects sorted by display name.

    Parameters
    ----------
    directory:
        Path to the folder containing ROM/ISO/CHD files.
    recursive:
        When *True*, descend into sub-directories.  Defaults to *False*
        because most users keep all ISOs in a single flat folder.

    Returns
    -------
    list[GameEntry]
        Discovered entries, sorted by :attr:`GameEntry.display_name`.
        An empty list is returned if *directory* does not exist or is empty.
    """
    root = Path(directory)
    if not root.is_dir():
        log.debug("game_library: directory not found: %s", directory)
        return []

    entries: List[GameEntry] = []
    seen_paths: set = set()

    walk_fn = os.walk if recursive else _flat_walk
    for dirpath, _dirs, filenames in walk_fn(str(root)):
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext not in GAME_EXTENSIONS:
                continue

            full = str(Path(dirpath) / fname)
            if full in seen_paths:
                continue
            seen_paths.add(full)

            serial = detect_game_serial(fname)
            if not serial:
                # Try detecting from the full path (e.g. if folder name contains serial)
                serial = detect_game_serial(full)

            title = ""
            crcs: List[str] = []
            if serial:
                display = serial_to_display(serial)
                # serial_to_display returns "SERIAL — Title" or just "SERIAL"
                if " — " in display:
                    title = display.split(" — ", 1)[1]
                crcs = _get_sdb().crcs_for_serial(serial)

            try:
                size = Path(full).stat().st_size
            except OSError:
                size = 0

            entries.append(GameEntry(
                path=full,
                filename=fname,
                serial=serial,
                title=title,
                size_bytes=size,
                crcs=crcs,
            ))

    entries.sort(key=lambda e: e.display_name.lower())
    log.debug("game_library: found %d file(s) in %s", len(entries), directory)
    return entries


def get_library_serials(directory: str) -> frozenset:
    """Return a frozenset of all detected serials in *directory*.

    Serials are upper-cased and normalised (dash separator).
    Empty-string serials (undetected) are excluded.
    """
    return frozenset(
        e.serial.upper()
        for e in scan_library(directory)
        if e.serial
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flat_walk(root: str):
    """Yield a single ``(dirpath, dirs, files)`` tuple for the top-level
    directory only — equivalent to ``os.walk`` with depth=1."""
    p = Path(root)
    try:
        names = list(os.scandir(root))
    except PermissionError:
        return
    files = [e.name for e in names if e.is_file(follow_symlinks=True)]
    dirs = [e.name for e in names if e.is_dir(follow_symlinks=True)]
    yield str(p), dirs, files
