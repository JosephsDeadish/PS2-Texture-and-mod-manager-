"""Backup and restore utilities for PS2 Mod Manager.

Creates timestamped ZIP archives of the PCSX2 managed data directories
(PNACH cheats, cover art, texture packs) and restores from those archives.

Backups are stored in a ``backups/`` sub-folder next to the application
executable (the same root as ``user_catalogue/``).

Public API::

    from src.core.backup_manager import (
        BackupEntry,
        get_backup_dir,
        create_backup,
        list_backups,
        restore_backup,
        delete_backup,
    )

    entry = create_backup(config, note="before big update")
    print(entry.label, entry.size_label)

    for e in list_backups(config):
        print(e.created_at, e.label)

    restore_backup(entry, config)
    delete_backup(entry)
"""

from __future__ import annotations

import datetime
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Sub-directory name (relative to the exe directory) used for all archives.
BACKUP_SUBDIR = "backups"


# ---------------------------------------------------------------------------
# BackupEntry dataclass
# ---------------------------------------------------------------------------

@dataclass
class BackupEntry:
    """Metadata for a single backup archive.

    Attributes
    ----------
    path:
        Absolute path to the ``.zip`` archive on disk.
    label:
        Human-readable filename (``backup_YYYYMMDD_HHMMSS[_note].zip``).
    created_at:
        ISO-8601 timestamp string (seconds precision).
    size_bytes:
        Total *uncompressed* size of all archived files in bytes.
    note:
        Optional user note embedded in the archive filename.
    """

    path: str
    label: str
    created_at: str
    size_bytes: int
    note: str = ""

    @property
    def size_label(self) -> str:
        """Human-readable size string (e.g. ``~12 MB``)."""
        mb = self.size_bytes / (1024 * 1024)
        if mb >= 1024:
            return f"~{mb / 1024:.1f} GB"
        if mb >= 1:
            return f"~{mb:.0f} MB"
        kb = self.size_bytes / 1024
        return f"~{kb:.0f} KB"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_backup_dir(config) -> Path:
    """Return the backup directory, creating it if it does not yet exist.

    Parameters
    ----------
    config:
        Any object; not used for path resolution (the backup dir is always
        placed next to the executable).  Kept for API symmetry with the
        other functions.
    """
    from src.core.config_manager import get_exe_dir
    backup_dir = Path(get_exe_dir()) / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _collect_paths(config) -> List[Path]:
    """Return the list of existing PCSX2 data directories to back up."""
    paths: List[Path] = []
    for attr in ("pnach_path", "cheats_path", "cover_art_path", "textures_path"):
        raw = getattr(config, attr, "") or ""
        if raw:
            p = Path(raw)
            if p.exists():
                paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_backup(config, note: str = "") -> BackupEntry:
    """Create a ZIP backup of PCSX2 managed data directories.

    The archive is written to ``<exe_dir>/backups/backup_YYYYMMDD_HHMMSS.zip``
    (or ``backup_YYYYMMDD_HHMMSS_<note>.zip`` when *note* is provided).

    Only directories that exist at the time of the call are included.  An
    empty archive is created if none of the configured paths exist.

    Parameters
    ----------
    config:
        :class:`~src.models.mod.AppConfig` (or any object) with
        ``pnach_path``, ``cheats_path``, ``cover_art_path`` and
        ``textures_path`` attributes.
    note:
        Optional short note to embed in the filename (alphanumeric / spaces
        / hyphens / underscores only; truncated to 40 characters).

    Returns
    -------
    BackupEntry
        Metadata for the newly-created archive.
    """
    backup_dir = get_backup_dir(config)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Sanitise the note for use in a filename.
    safe_note = (
        "".join(c for c in note if c.isalnum() or c in " _-")[:40]
        .strip()
        .replace(" ", "_")
    )
    filename = "backup_" + ts + (f"_{safe_note}" if safe_note else "") + ".zip"
    zip_path = backup_dir / filename

    paths_to_include = _collect_paths(config)
    total_size = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for folder in paths_to_include:
            folder_name = folder.name
            for item in sorted(folder.rglob("*")):
                if item.is_file():
                    arcname = folder_name + "/" + str(item.relative_to(folder))
                    zf.write(item, arcname)
                    total_size += item.stat().st_size

    created_at = datetime.datetime.now().isoformat(timespec="seconds")
    return BackupEntry(
        path=str(zip_path),
        label=filename,
        created_at=created_at,
        size_bytes=total_size,
        note=note,
    )


def list_backups(config) -> List[BackupEntry]:
    """Return all existing backup archives sorted newest-first.

    Parameters
    ----------
    config:
        Used only to locate the backup directory via :func:`get_backup_dir`.
    """
    backup_dir = get_backup_dir(config)
    entries: List[BackupEntry] = []

    for zp in sorted(backup_dir.glob("backup_*.zip"), reverse=True):
        stat = zp.stat()
        try:
            with zipfile.ZipFile(zp) as zf:
                size_bytes = sum(i.file_size for i in zf.infolist())
        except Exception:
            size_bytes = stat.st_size

        entries.append(
            BackupEntry(
                path=str(zp),
                label=zp.name,
                created_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                ),
                size_bytes=size_bytes,
            )
        )
    return entries


def restore_backup(entry: BackupEntry, config) -> int:
    """Extract a backup archive into the appropriate PCSX2 directories.

    Each top-level folder inside the archive is matched by name to the
    configured PCSX2 directories.  Unknown top-level folders are silently
    skipped so that archives remain forward-compatible.

    Parameters
    ----------
    entry:
        A :class:`BackupEntry` obtained from :func:`list_backups` or
        :func:`create_backup`.
    config:
        :class:`~src.models.mod.AppConfig` providing destination paths.

    Returns
    -------
    int
        Number of files that were restored.

    Raises
    ------
    FileNotFoundError
        If the archive ``.zip`` file no longer exists on disk.
    """
    zip_path = Path(entry.path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {zip_path}")

    # Build a map: archive top-level folder name → destination root path.
    folder_map: dict = {}
    for attr in ("pnach_path", "cheats_path", "cover_art_path", "textures_path"):
        raw = getattr(config, attr, "") or ""
        if raw:
            dest = Path(raw)
            folder_map[dest.name] = dest

    restored = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if len(parts) < 2:
                continue
            top_folder, rel_path = parts
            dest_root = folder_map.get(top_folder)
            if dest_root is None:
                continue
            dest_file = dest_root / rel_path
            # Guard against zip-slip: reject any path that escapes dest_root.
            try:
                dest_file.resolve().relative_to(dest_root.resolve())
            except ValueError:
                continue
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest_file, "wb") as dst:
                dst.write(src.read())
            restored += 1

    return restored


def delete_backup(entry: BackupEntry) -> bool:
    """Delete a backup archive from disk.

    Parameters
    ----------
    entry:
        A :class:`BackupEntry` to remove.

    Returns
    -------
    bool
        ``True`` on success, ``False`` if the file could not be deleted.
    """
    try:
        Path(entry.path).unlink()
        return True
    except Exception:
        return False
