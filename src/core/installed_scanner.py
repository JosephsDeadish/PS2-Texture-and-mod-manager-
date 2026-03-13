"""Installed-content scanner for PS2 Mod Manager.

This module detects content (texture packs, PNACH patches, cheats, cover art,
and memory-card saves) that already exists inside the PCSX2 directory tree but
was *not* installed through PS2 Mod Manager.  Such "unmanaged" items can then
be registered with the manager so they can be toggled, combined, or replaced
just like any other installed mod.

Typical PCSX2 layout handled by this module::

    <pcsx2_root>/
    ├── cheats/            ← .pnach files not tracked by the manager
    ├── cheats_ws/         ← widescreen .pnach files
    ├── covers/            ← cover-art images (SERIAL.png)
    ├── memcards/          ← memory-card files (.ps2 / .mcd)
    └── textures/
        └── <SERIAL>/
            └── replacements/   ← texture-pack files

Public API::

    from src.core.installed_scanner import (
        UnmanagedItem,
        scan_all,
        scan_pnach,
        scan_cheats,
        scan_cover_art,
        scan_textures,
    )

    items = scan_all(config)
    for item in items:
        print(item.item_type, item.name, item.path)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from src.models.mod import ModType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Matches PS2 disc serials in the form XX(X)-NNNNN, case-insensitive.
_PS2_SERIAL_RE = re.compile(r'^[A-Z]{2,4}-\d{3,5}$', re.IGNORECASE)

#: Matches an 8-hex-digit CRC filename (e.g. F0A235B4.pnach)
_CRC_PNACH_RE = re.compile(r'^[0-9A-Fa-f]{8}\.pnach$')


def _is_ps2_serial(name: str) -> bool:
    return bool(_PS2_SERIAL_RE.match(name))


def _dir_size_and_count(path: Path):
    """Return ``(total_bytes, file_count)`` for all files under *path*."""
    total = 0
    count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for fname in files:
                try:
                    total += (Path(root) / fname).stat().st_size
                    count += 1
                except OSError:
                    pass
    except PermissionError:
        pass
    return total, count


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _size_label(size_bytes: int) -> str:
    b = size_bytes
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.0f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


def _game_title(serial: str) -> str:
    """Lookup game title for a serial, returns empty string if unknown."""
    try:
        from src.core.game_registry import lookup_game_title
        return lookup_game_title(serial.upper()) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class UnmanagedItem:
    """A pre-existing PCSX2 content item that is not tracked by the mod manager.

    Attributes
    ----------
    item_type:
        The :class:`~src.models.mod.ModType` that best describes this item.
    name:
        A short human-readable label (e.g. filename, serial).
    path:
        Absolute path to the file or directory.
    size_bytes:
        Total size of the item in bytes.
    file_count:
        Number of files (1 for single-file items like PNACH / cover art).
    serial:
        PS2 disc serial associated with the item if known (e.g. ``"SLUS-20062"``).
    suggested_game:
        Game title suggested from the built-in game registry (may be empty).
    crc:
        For PNACH items: the 8-char hex CRC string from the filename.
    catalogue_matches:
        Catalogue entry IDs that might correspond to this item (filled by the
        caller after a catalogue search — not populated by the scanner itself).
    """

    item_type: ModType
    name: str
    path: Path
    size_bytes: int = 0
    file_count: int = 1
    serial: str = ""
    suggested_game: str = ""
    crc: str = ""
    catalogue_matches: List[str] = field(default_factory=list)

    @property
    def size_label(self) -> str:
        return _size_label(self.size_bytes)

    @property
    def type_label(self) -> str:
        _MAP = {
            ModType.TEXTURE_PACK: "Texture Pack",
            ModType.PNACH:        "PNACH Patch",
            ModType.CHEAT:        "Widescreen Patch",
            ModType.COVER_ART:    "Cover Art",
            ModType.SAVE_FILE:    "Memory Card Save",
        }
        return _MAP.get(self.item_type, self.item_type.value)


# ---------------------------------------------------------------------------
# Per-type scanners
# ---------------------------------------------------------------------------

def scan_pnach(
    pnach_path: str,
    managed_paths: Optional[Set[str]] = None,
) -> List[UnmanagedItem]:
    """Scan *pnach_path* (PCSX2 ``cheats/`` folder) for unmanaged ``.pnach`` files.

    Only files whose name is an 8-hex-digit CRC are considered valid PNACH
    files (e.g. ``F0A235B4.pnach``).

    Parameters
    ----------
    pnach_path:
        Path to PCSX2's ``cheats/`` directory.
    managed_paths:
        Set of absolute path strings already tracked by the mod database.
        These are excluded from results.

    Returns
    -------
    list[UnmanagedItem]
        One entry per unmanaged ``.pnach`` file, sorted by CRC.
    """
    if not pnach_path:
        return []
    root = Path(pnach_path)
    if not root.is_dir():
        return []

    managed = {str(Path(p).resolve()) for p in (managed_paths or set())}
    results: List[UnmanagedItem] = []

    try:
        files = sorted(root.iterdir())
    except PermissionError:
        return []

    for f in files:
        if not f.is_file():
            continue
        if not _CRC_PNACH_RE.match(f.name):
            continue
        resolved = str(f.resolve())
        if resolved in managed:
            continue

        crc = f.stem.upper()
        results.append(UnmanagedItem(
            item_type=ModType.PNACH,
            name=f.name,
            path=f,
            size_bytes=_file_size(f),
            file_count=1,
            crc=crc,
        ))

    return results


def scan_cheats(
    cheats_path: str,
    managed_paths: Optional[Set[str]] = None,
) -> List[UnmanagedItem]:
    """Scan *cheats_path* (PCSX2 ``cheats_ws/`` folder) for unmanaged widescreen/cheat
    ``.pnach`` files.

    The same CRC-filename convention applies.

    Parameters
    ----------
    cheats_path:
        Path to PCSX2's ``cheats_ws/`` directory (or alternate cheats folder).
    managed_paths:
        Set of absolute path strings already tracked by the mod database.

    Returns
    -------
    list[UnmanagedItem]
        One entry per unmanaged widescreen ``.pnach`` file, sorted by CRC.
    """
    if not cheats_path:
        return []
    root = Path(cheats_path)
    if not root.is_dir():
        return []

    managed = {str(Path(p).resolve()) for p in (managed_paths or set())}
    results: List[UnmanagedItem] = []

    try:
        files = sorted(root.iterdir())
    except PermissionError:
        return []

    for f in files:
        if not f.is_file():
            continue
        if not _CRC_PNACH_RE.match(f.name):
            continue
        resolved = str(f.resolve())
        if resolved in managed:
            continue

        crc = f.stem.upper()
        results.append(UnmanagedItem(
            item_type=ModType.CHEAT,
            name=f.name,
            path=f,
            size_bytes=_file_size(f),
            file_count=1,
            crc=crc,
        ))

    return results


def scan_cover_art(
    cover_art_path: str,
    managed_paths: Optional[Set[str]] = None,
) -> List[UnmanagedItem]:
    """Scan *cover_art_path* (PCSX2 ``covers/`` folder) for unmanaged cover images.

    PCSX2 stores cover art as ``<SERIAL>.png`` (or ``.jpg`` / ``.jpeg``).
    Only files whose base name matches a PS2 serial are returned.

    Parameters
    ----------
    cover_art_path:
        Path to PCSX2's ``covers/`` directory.
    managed_paths:
        Set of absolute path strings already tracked by the mod database.

    Returns
    -------
    list[UnmanagedItem]
        One entry per unmanaged cover image, sorted by serial.
    """
    if not cover_art_path:
        return []
    root = Path(cover_art_path)
    if not root.is_dir():
        return []

    managed = {str(Path(p).resolve()) for p in (managed_paths or set())}
    results: List[UnmanagedItem] = []

    try:
        files = sorted(root.iterdir())
    except PermissionError:
        return []

    for f in files:
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        serial = f.stem.upper()
        if not _is_ps2_serial(serial):
            continue
        resolved = str(f.resolve())
        if resolved in managed:
            continue

        suggested = _game_title(serial)
        results.append(UnmanagedItem(
            item_type=ModType.COVER_ART,
            name=f.name,
            path=f,
            size_bytes=_file_size(f),
            file_count=1,
            serial=serial,
            suggested_game=suggested,
        ))

    return results


def scan_textures(
    textures_path: str,
    managed_paths: Optional[Set[str]] = None,
) -> List[UnmanagedItem]:
    """Scan *textures_path* for unmanaged texture packs.

    Delegates to :func:`~src.core.texture_scanner.scan_unmanaged_texture_packs`
    and converts results to :class:`UnmanagedItem` objects.

    Parameters
    ----------
    textures_path:
        Path to PCSX2's ``textures/`` directory.
    managed_paths:
        Set of absolute path strings already tracked by the mod database.

    Returns
    -------
    list[UnmanagedItem]
        One entry per unmanaged texture pack directory, sorted by serial.
    """
    from src.core.texture_scanner import scan_unmanaged_texture_packs
    packs = scan_unmanaged_texture_packs(textures_path, managed_paths)
    results: List[UnmanagedItem] = []
    for pack in packs:
        results.append(UnmanagedItem(
            item_type=ModType.TEXTURE_PACK,
            name=f"{pack.serial} Texture Pack",
            path=pack.path,
            size_bytes=pack.size_bytes,
            file_count=pack.file_count,
            serial=pack.serial,
            suggested_game=pack.suggested_game,
        ))
    return results


def scan_all(config, managed_paths: Optional[Set[str]] = None) -> List[UnmanagedItem]:
    """Scan all PCSX2 content directories for unmanaged items.

    Runs all individual scanners (:func:`scan_textures`, :func:`scan_pnach`,
    :func:`scan_cheats`, :func:`scan_cover_art`) and returns a combined list
    sorted by type then name.

    Parameters
    ----------
    config:
        An :class:`~src.models.mod.AppConfig` instance (or any object with the
        attributes ``textures_path``, ``pnach_path``, ``cheats_path``,
        ``cover_art_path``).
    managed_paths:
        Set of absolute path strings already tracked by the mod database.
        Pass ``None`` to return every unmanaged item found.

    Returns
    -------
    list[UnmanagedItem]
        All unmanaged items across all scan types.
    """
    results: List[UnmanagedItem] = []

    textures_path = getattr(config, "textures_path", "") or ""
    pnach_path    = getattr(config, "pnach_path", "")    or ""
    cheats_path   = getattr(config, "cheats_path", "")   or ""
    cover_art_path = getattr(config, "cover_art_path", "") or ""

    results.extend(scan_textures(textures_path, managed_paths))
    results.extend(scan_pnach(pnach_path, managed_paths))
    results.extend(scan_cheats(cheats_path, managed_paths))
    results.extend(scan_cover_art(cover_art_path, managed_paths))

    return results


# ---------------------------------------------------------------------------
# Catalogue matching helper
# ---------------------------------------------------------------------------

def find_catalogue_matches(
    item: UnmanagedItem,
    catalogue: list,
    *,
    limit: int = 5,
) -> List[dict]:
    """Return up to *limit* catalogue entries that could match *item*.

    Matching is done by comparing the item's serial and/or game title against
    catalogue entry ``game_serial`` and ``game`` fields.  Results are sorted by
    relevance (serial match first, then name substring match).

    Parameters
    ----------
    item:
        The unmanaged item to find matches for.
    catalogue:
        Full catalogue list (list of entry dicts), e.g. from
        :data:`src.core.catalogue_loader.CATALOGUE`.
    limit:
        Maximum number of matches to return.

    Returns
    -------
    list[dict]
        Matching catalogue entry dicts, most relevant first.
    """
    serial_upper = item.serial.upper() if item.serial else ""
    game_lower   = item.suggested_game.lower() if item.suggested_game else ""

    by_serial: List[dict] = []
    by_game:   List[dict] = []

    for entry in catalogue:
        # Only consider same type
        if entry.get("type") and entry["type"] != item.item_type:
            continue
        entry_serial = str(entry.get("game_serial", "")).upper()
        entry_game   = str(entry.get("game", "")).lower()

        if serial_upper and entry_serial == serial_upper:
            by_serial.append(entry)
        elif game_lower and game_lower in entry_game:
            by_game.append(entry)

    combined: List[dict] = []
    seen: set = set()
    for e in by_serial + by_game:
        eid = e.get("id")
        if eid and eid not in seen:
            seen.add(eid)
            combined.append(e)
        if len(combined) >= limit:
            break

    return combined
