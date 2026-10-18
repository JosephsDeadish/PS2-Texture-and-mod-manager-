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

import logging
import datetime
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

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
    file_count: int = 0
    failure_count: int = 0
    inspection_error: str = ""

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


@dataclass
class RestoreReport:
    """Detailed outcome; legacy restore callers still receive an integer."""

    restored: int = 0
    failed: int = 0
    skipped: int = 0


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
    Collisions receive a numeric suffix; existing files are never replaced.

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

    fd, tmp_name = tempfile.mkstemp(dir=backup_dir, suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    reserved = False
    try:
        failures = 0
        written_files = 0
        first_error: Exception | None = None
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for folder in paths_to_include:
                folder_name = folder.name
                try:
                    items = sorted(folder.rglob("*"))
                except OSError as exc:
                    failures += 1
                    if first_error is None:
                        first_error = exc
                    logger.warning("Failed to enumerate backup folder %s: %s", folder, exc)
                    continue
                for item in items:
                    if item.is_file():
                        arcname = folder_name + "/" + str(item.relative_to(folder))
                        try:
                            zf.write(item, arcname)
                            written_files += 1
                        except OSError as exc:
                            failures += 1
                            if first_error is None:
                                first_error = exc
                            logger.warning("Failed to add backup file %s: %s", item, exc)
                            continue
                        try:
                            total_size += item.stat().st_size
                        except OSError as exc:
                            failures += 1
                            if first_error is None:
                                first_error = exc
                            logger.warning("Failed to inspect backup file %s after archiving: %s", item, exc)
        if failures and written_files:
            logger.warning(
                "Created backup archive %s with %s recoverable failure(s)",
                zip_path,
                failures,
            )
        if first_error is not None and written_files == 0:
            raise first_error
        for attempt in range(10000):
            suffix = f"_{attempt}" if attempt else ""
            zip_path = backup_dir / f"{Path(filename).stem}{suffix}.zip"
            try:
                with zip_path.open("xb"):
                    pass
            except FileExistsError:
                continue
            reserved = True
            os.replace(tmp_path, zip_path)
            break
        else:
            raise FileExistsError("Too many backup filename collisions")
    except Exception as exc:
        logger.warning("Failed to create backup archive %s: %s", zip_path, exc)
        try:
            tmp_path.unlink()
        except OSError as cleanup_exc:
            logger.warning("Could not remove temporary backup archive %s: %s", tmp_path, cleanup_exc)
        if reserved:
            try:
                zip_path.unlink()
            except OSError as cleanup_exc:
                logger.warning("Could not remove incomplete backup %s: %s", zip_path, cleanup_exc)
        raise

    created_at = datetime.datetime.now().isoformat(timespec="seconds")
    return BackupEntry(
        path=str(zip_path),
        label=zip_path.name,
        created_at=created_at,
        size_bytes=total_size,
        note=note,
        file_count=written_files,
        failure_count=failures,
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

    for zp in sorted(backup_dir.iterdir(), reverse=True):
        if not (zp.name.startswith("backup_") and zp.name.endswith(".zip")):
            continue
        try:
            stat = zp.stat()
        except OSError as exc:
            logger.warning("Failed to inspect backup archive metadata %s: %s", zp, exc)
            continue
        inspection_error = ""
        file_count = 0
        try:
            with zipfile.ZipFile(zp) as zf:
                size_bytes = sum(i.file_size for i in zf.infolist())
                file_count = sum(not i.is_dir() for i in zf.infolist())
        except Exception as exc:
            logger.warning("Failed to inspect backup archive %s: %s", zp, exc)
            size_bytes = stat.st_size
            inspection_error = str(exc)

        entries.append(
            BackupEntry(
                path=str(zp),
                label=zp.name,
                created_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                ),
                size_bytes=size_bytes,
                file_count=file_count,
                inspection_error=inspection_error,
            )
        )
    return entries


def restore_backup(entry: BackupEntry, config, *, detailed: bool = False) -> int | RestoreReport:
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
    int or RestoreReport
        Number of files restored, or counts of restored, failed and skipped
        files when ``detailed=True``. Skipped files include unknown folders
        and unsafe paths.

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
    failures = 0
    skipped = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.split("/", 1)
                if len(parts) < 2:
                    skipped += 1
                    continue
                top_folder, rel_path = parts
                dest_root = folder_map.get(top_folder)
                if dest_root is None:
                    skipped += 1
                    continue
                dest_file = dest_root / rel_path
                # Guard against zip-slip: reject any path that escapes dest_root.
                try:
                    dest_file.resolve().relative_to(dest_root.resolve())
                except ValueError:
                    skipped += 1
                    logger.warning(
                        "Skipping backup archive entry outside destination %s: %s",
                        dest_root,
                        info.filename,
                    )
                    continue
                try:
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                except Exception as exc:
                    failures += 1
                    logger.warning(
                        "Failed to restore backup entry %s to %s: %s",
                        info.filename,
                        dest_file,
                        exc,
                    )
                    continue
                restored += 1
    except Exception as exc:
        logger.warning("Failed to restore backup archive %s: %s", zip_path, exc)
        raise

    if failures:
        logger.warning(
            "Restored %s file(s) from %s with %s failure(s)",
            restored,
            zip_path,
            failures,
        )

    return RestoreReport(restored, failures, skipped) if detailed else restored


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
    except Exception as exc:
        logger.warning("Failed to delete backup %s: %s", entry.path, exc)
        return False
