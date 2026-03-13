"""Texture pack scanner for PS2 Mod Manager.

This module detects texture packs that are already present in the PCSX2
``textures/`` directory but were not installed through PS2 Mod Manager.

Such "unmanaged" packs can be registered with the mod manager so they can
be toggled, combined, or replaced just like any other installed mod.

Typical layout detected::

    <textures_root>/
    └── SLUS-20062/
        ├── replacements/      ← unmanaged textures live here
        └── dumps/

Public API::

    from src.core.texture_scanner import UnmanagedPack, scan_unmanaged_texture_packs

    packs = scan_unmanaged_texture_packs(
        textures_root="/path/to/pcsx2/textures",
        managed_paths=set(),    # paths already tracked by the mod DB
    )
    for pack in packs:
        print(pack.serial, pack.path, pack.file_count, pack.size_bytes)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

# ---------------------------------------------------------------------------
# PS2 serial pattern
# ---------------------------------------------------------------------------

#: Matches PS2 disc serials in the form XX(X)-NNNNN, case-insensitive.
_PS2_SERIAL_RE = re.compile(r'^[A-Z]{2,4}-\d{3,5}$', re.IGNORECASE)


def _is_ps2_serial(name: str) -> bool:
    """Return *True* if *name* looks like a PS2 disc serial."""
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


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class UnmanagedPack:
    """A texture pack found in the PCSX2 textures directory that is not yet
    tracked by the PS2 Mod Manager mod database.

    Attributes
    ----------
    serial:
        PS2 disc serial (folder name), e.g. ``"SLUS-20062"``.
    path:
        Absolute path to the ``replacements/`` sub-folder containing the
        unmanaged textures.
    file_count:
        Number of texture files found directly under *path*.
    size_bytes:
        Total size of all files under *path* in bytes.
    suggested_game:
        Game title suggested from the built-in game registry (may be empty
        if the serial is not recognised).
    """

    serial: str
    path: Path
    file_count: int = 0
    size_bytes: int = 0
    suggested_game: str = ""

    @property
    def size_label(self) -> str:
        """Human-readable size string (e.g. ``"~250 MB"``)."""
        b = self.size_bytes
        if b < 1024:
            return f"{b} B"
        if b < 1024 ** 2:
            return f"{b / 1024:.1f} KB"
        if b < 1024 ** 3:
            return f"{b / 1024 ** 2:.0f} MB"
        return f"{b / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_unmanaged_texture_packs(
    textures_root: str,
    managed_paths: Optional[Set[str]] = None,
) -> List[UnmanagedPack]:
    """Scan *textures_root* for texture packs not tracked by the mod manager.

    PCSX2 stores texture replacements under::

        <textures_root>/<SERIAL>/replacements/

    This function walks the top-level directories of *textures_root*, looks
    for any ``<SERIAL>/replacements/`` sub-folders that contain at least one
    file, and returns those that are **not** already listed in *managed_paths*.

    Parameters
    ----------
    textures_root:
        Path to the PCSX2 ``textures/`` directory (value of
        ``config.textures_path``).
    managed_paths:
        Set of absolute path strings already tracked by
        :class:`~src.core.mod_manager.ModDatabase`.  These are excluded from
        the results so that properly installed packs are not reported as
        unmanaged.  Pass ``None`` or an empty set to return every pack found.

    Returns
    -------
    list[UnmanagedPack]
        One entry per ``<SERIAL>/replacements/`` directory that has at least
        one texture file and is not in *managed_paths*.  Sorted by serial.
    """
    if not textures_root:
        return []

    root = Path(textures_root)
    if not root.is_dir():
        return []

    managed = {str(Path(p).resolve()) for p in (managed_paths or set())}

    # Try to import game registry for title lookup
    try:
        from src.core.game_registry import lookup_game_title as get_game_title
    except Exception:
        get_game_title = None  # type: ignore[assignment]

    results: List[UnmanagedPack] = []

    try:
        candidates = sorted(root.iterdir())
    except PermissionError:
        return []

    for serial_dir in candidates:
        if not serial_dir.is_dir():
            continue
        if not _is_ps2_serial(serial_dir.name):
            continue

        replacements = serial_dir / "replacements"
        if not replacements.is_dir():
            # Some packs store textures directly under the serial folder
            replacements = serial_dir

        resolved = str(replacements.resolve())
        if resolved in managed:
            continue

        size_bytes, file_count = _dir_size_and_count(replacements)
        if file_count == 0:
            continue  # empty directory — nothing to manage

        suggested = ""
        if get_game_title is not None:
            try:
                suggested = get_game_title(serial_dir.name.upper()) or ""
            except Exception:
                suggested = ""

        results.append(
            UnmanagedPack(
                serial=serial_dir.name.upper(),
                path=replacements,
                file_count=file_count,
                size_bytes=size_bytes,
                suggested_game=suggested,
            )
        )

    return results
