"""Download / installation event history for PS2 Mod Manager.

Every time a mod, texture pack, PNACH patch, cover-art image or game-save
file is successfully (or unsuccessfully) installed through the manager, a
:class:`HistoryEntry` is appended to the persistent JSON log stored next to
the application executable.

Public API::

    from src.core.download_history import (
        HistoryEntry,
        STATUS_SUCCESS,
        STATUS_FAILED,
        STATUS_SKIPPED,
        get_history_file,
        record_event,
        list_history,
        clear_history,
        delete_entry,
        export_history_csv,
    )

    # Record a successful installation
    entry = record_event(
        config,
        mod_name="Silent Hill 2 HD Texture Pack",
        mod_type="texture_pack",
        serial="SLUS-20228",
        source_url="https://gbatemp.net/threads/...",
        status=STATUS_SUCCESS,
        size_bytes=52_428_800,
        note="installed from browse panel",
    )
    print(entry.timestamp, entry.status_label)

    # Retrieve last 50 entries
    entries = list_history(config, limit=50)

    # Export to CSV
    csv_path = export_history_csv(config)
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED  = "failed"
STATUS_SKIPPED = "skipped"

# ---------------------------------------------------------------------------
# Human-readable labels / colours
# ---------------------------------------------------------------------------

STATUS_LABEL: dict = {
    STATUS_SUCCESS: "✅ Success",
    STATUS_FAILED:  "❌ Failed",
    STATUS_SKIPPED: "⏭ Skipped",
}

STATUS_COLOR: dict = {
    STATUS_SUCCESS: "#27ae60",
    STATUS_FAILED:  "#c0392b",
    STATUS_SKIPPED: "#7f8c8d",
}

MOD_TYPE_LABEL: dict = {
    "texture_pack": "🎨 Texture Pack",
    "pnach":        "🔧 PNACH Patch",
    "cover_art":    "🖼 Cover Art",
    "save":         "💾 Game Save",
    "cheat":        "🕹 Cheat",
    "other":        "📦 Other",
}

# Sub-directory name (relative to the exe directory) for the history log.
HISTORY_FILENAME = "download_history.json"

# Maximum entries retained in the log before the oldest are pruned on save.
MAX_HISTORY_ENTRIES = 500


# ---------------------------------------------------------------------------
# HistoryEntry dataclass
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """A single download / installation event.

    Attributes
    ----------
    id:
        Unique identifier (UUID4 string).
    timestamp:
        ISO-8601 timestamp with second precision (UTC).
    mod_name:
        Human-readable name of the installed item.
    mod_type:
        One of ``"texture_pack"``, ``"pnach"``, ``"cover_art"``,
        ``"save"``, ``"cheat"``, ``"other"``.
    serial:
        PS2 disc serial the mod targets (e.g. ``"SLUS-20228"``), or empty.
    source_url:
        URL from which the mod was downloaded, or empty.
    status:
        One of :data:`STATUS_SUCCESS`, :data:`STATUS_FAILED`,
        :data:`STATUS_SKIPPED`.
    size_bytes:
        Installed size in bytes (0 when unknown).
    note:
        Optional free-text note.
    """

    id:         str
    timestamp:  str
    mod_name:   str
    mod_type:   str
    serial:     str  = ""
    source_url: str  = ""
    status:     str  = STATUS_SUCCESS
    size_bytes: int  = 0
    note:       str  = ""

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def status_label(self) -> str:
        """Human-readable status (e.g. ``"✅ Success"``)."""
        return STATUS_LABEL.get(self.status, self.status)

    @property
    def type_label(self) -> str:
        """Human-readable mod type (e.g. ``"🎨 Texture Pack"``)."""
        return MOD_TYPE_LABEL.get(self.mod_type, "📦 Other")

    @property
    def size_label(self) -> str:
        """Human-readable size (e.g. ``"~52 MB"``) or ``"–"`` when unknown."""
        if self.size_bytes <= 0:
            return "–"
        mb = self.size_bytes / (1024 * 1024)
        if mb >= 1024:
            return f"~{mb / 1024:.1f} GB"
        if mb >= 1:
            return f"~{mb:.0f} MB"
        kb = self.size_bytes / 1024
        if kb >= 1:
            return f"~{kb:.0f} KB"
        return f"{self.size_bytes} B"

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "timestamp":  self.timestamp,
            "mod_name":   self.mod_name,
            "mod_type":   self.mod_type,
            "serial":     self.serial,
            "source_url": self.source_url,
            "status":     self.status,
            "size_bytes": self.size_bytes,
            "note":       self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            id         = d.get("id", str(uuid.uuid4())),
            timestamp  = d.get("timestamp", ""),
            mod_name   = d.get("mod_name", ""),
            mod_type   = d.get("mod_type", "other"),
            serial     = d.get("serial", ""),
            source_url = d.get("source_url", ""),
            status     = d.get("status", STATUS_SUCCESS),
            size_bytes = int(d.get("size_bytes", 0)),
            note       = d.get("note", ""),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_history_file(config=None) -> Path:
    """Return the absolute path to the history JSON log.

    The file is stored next to the application executable (same root as the
    ``backups/`` and ``user_catalogue/`` directories).

    Parameters
    ----------
    config:
        Not used for path resolution; kept for API symmetry.
    """
    from src.core.config_manager import get_exe_dir
    return Path(get_exe_dir()) / HISTORY_FILENAME


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load(config=None) -> List[HistoryEntry]:
    """Return all history entries from disk, newest first.  Never raises."""
    path = get_history_file(config)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return [HistoryEntry.from_dict(d) for d in raw if isinstance(d, dict)]
    except Exception:
        return []


def _save(entries: List[HistoryEntry], config=None) -> None:
    """Persist *entries* to disk atomically, pruning to :data:`MAX_HISTORY_ENTRIES`."""
    path = get_history_file(config)
    to_write = entries[:MAX_HISTORY_ENTRIES]
    data = [e.to_dict() for e in to_write]
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_event(
    config,
    mod_name:   str,
    mod_type:   str,
    serial:     str = "",
    source_url: str = "",
    status:     str = STATUS_SUCCESS,
    size_bytes: int = 0,
    note:       str = "",
) -> HistoryEntry:
    """Append a new event to the history log and return the created entry.

    Parameters
    ----------
    config:
        Application configuration (used only to locate the log file).
    mod_name:
        Human-readable name of the item (e.g. ``"Silent Hill 2 HD"``).
    mod_type:
        Category string: ``"texture_pack"``, ``"pnach"``, ``"cover_art"``,
        ``"save"``, ``"cheat"``, or ``"other"``.
    serial:
        PS2 disc serial (optional, e.g. ``"SLUS-20228"``).
    source_url:
        Download origin URL (optional).
    status:
        :data:`STATUS_SUCCESS`, :data:`STATUS_FAILED`, or
        :data:`STATUS_SKIPPED`.
    size_bytes:
        Installed size in bytes (0 if unknown).
    note:
        Optional free-text annotation.

    Returns
    -------
    HistoryEntry
        The newly created and persisted entry.
    """
    entry = HistoryEntry(
        id         = str(uuid.uuid4()),
        timestamp  = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        mod_name   = mod_name,
        mod_type   = mod_type,
        serial     = serial,
        source_url = source_url,
        status     = status,
        size_bytes = size_bytes,
        note       = note,
    )
    entries = _load(config)
    entries.insert(0, entry)   # newest first
    _save(entries, config)
    return entry


def list_history(
    config,
    limit:    int = 0,
    status:   Optional[str] = None,
    mod_type: Optional[str] = None,
    serial:   Optional[str] = None,
) -> List[HistoryEntry]:
    """Return history entries, optionally filtered.

    Parameters
    ----------
    config:
        Application configuration.
    limit:
        Maximum number of entries to return (0 = no limit).
    status:
        If given, only entries with this status are returned.
    mod_type:
        If given, only entries of this mod type are returned.
    serial:
        If given, only entries for this disc serial are returned.

    Returns
    -------
    list[HistoryEntry]
        Entries sorted newest-first.
    """
    entries = _load(config)
    if status:
        entries = [e for e in entries if e.status == status]
    if mod_type:
        entries = [e for e in entries if e.mod_type == mod_type]
    if serial:
        entries = [e for e in entries if e.serial == serial]
    if limit and limit > 0:
        entries = entries[:limit]
    return entries


def clear_history(config) -> int:
    """Delete all history entries from disk.

    Returns
    -------
    int
        The number of entries that were removed.
    """
    entries = _load(config)
    count   = len(entries)
    _save([], config)
    return count


def delete_entry(entry: HistoryEntry, config) -> bool:
    """Remove a single entry from the history log.

    Parameters
    ----------
    entry:
        The entry to remove (matched by :attr:`HistoryEntry.id`).
    config:
        Application configuration.

    Returns
    -------
    bool
        ``True`` if an entry was found and removed, ``False`` otherwise.
    """
    entries = _load(config)
    new_entries = [e for e in entries if e.id != entry.id]
    if len(new_entries) == len(entries):
        return False
    _save(new_entries, config)
    return True


def export_history_csv(config, path: Optional[str] = None) -> str:
    """Export the full history log to a CSV file.

    Parameters
    ----------
    config:
        Application configuration (used to locate the log and default
        export location).
    path:
        Destination file path.  Defaults to ``download_history.csv`` placed
        next to the executable.

    Returns
    -------
    str
        Absolute path of the written CSV file.
    """
    from src.core.config_manager import get_exe_dir

    if not path:
        path = str(Path(get_exe_dir()) / "download_history.csv")

    entries = _load(config)
    fieldnames = [
        "id", "timestamp", "mod_name", "mod_type",
        "serial", "source_url", "status", "size_bytes", "note",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow(e.to_dict())

    return path
