"""Personal notes / annotations for catalogue entries.

Users can attach free-text notes to any catalogue entry (texture pack, PNACH
patch, cover-art download, game save, etc.).  Notes are stored in a single
JSON file next to the application executable.

Public API::

    from src.core.mod_notes import (
        NoteEntry,
        get_notes_file,
        upsert_note,
        get_note,
        list_notes,
        delete_note,
        clear_notes,
        export_notes_csv,
    )

    # Add or update a note for a catalogue entry
    note = upsert_note(
        config,
        entry_id="slus_20228_sh2_hd",
        entry_title="Silent Hill 2 HD Texture Pack",
        mod_type="texture_pack",
        serial="SLUS-20228",
        text="Installed v3.1 – looks amazing at 4K!",
    )
    print(note.updated_at, note.text)

    # Retrieve the note for a specific entry (or None)
    note = get_note(config, entry_id="slus_20228_sh2_hd")

    # List all notes, optionally filtered
    notes = list_notes(config, mod_type="texture_pack")

    # Delete a note
    deleted = delete_note(config, entry_id="slus_20228_sh2_hd")

    # Export all notes to CSV
    csv_path = export_notes_csv(config)
"""

from __future__ import annotations

import csv
import datetime
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTES_FILENAME = "mod_notes.json"

MOD_TYPE_LABEL: dict = {
    "texture_pack": "🎨 Texture Pack",
    "pnach":        "🔧 PNACH Patch",
    "cover_art":    "🖼 Cover Art",
    "save":         "💾 Game Save",
    "cheat":        "🕹 Cheat",
    "other":        "📦 Other",
}


# ---------------------------------------------------------------------------
# NoteEntry dataclass
# ---------------------------------------------------------------------------

@dataclass
class NoteEntry:
    """A personal annotation attached to a catalogue entry.

    Attributes
    ----------
    id:
        Unique identifier (UUID4 string) for this note record.
    entry_id:
        Stable identifier for the catalogue entry this note belongs to.
        Callers should derive a slug from the entry's title or URL so the
        same entry always maps to the same *entry_id*.
    entry_title:
        Human-readable name of the catalogue entry (e.g. the mod title).
    mod_type:
        Category: ``"texture_pack"``, ``"pnach"``, ``"cover_art"``,
        ``"save"``, ``"cheat"``, or ``"other"``.
    serial:
        PS2 disc serial (optional, e.g. ``"SLUS-20228"``).
    text:
        The note body written by the user.
    created_at:
        ISO-8601 timestamp when the note was first created.
    updated_at:
        ISO-8601 timestamp of the most recent edit.
    """

    id:          str
    entry_id:    str
    entry_title: str
    mod_type:    str
    serial:      str = ""
    text:        str = ""
    created_at:  str = ""
    updated_at:  str = ""

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def type_label(self) -> str:
        """Human-readable mod type label."""
        return MOD_TYPE_LABEL.get(self.mod_type, "📦 Other")

    @property
    def short_text(self) -> str:
        """First 80 characters of *text*, for use in list previews."""
        return self.text[:80] + ("…" if len(self.text) > 80 else "")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "entry_id":    self.entry_id,
            "entry_title": self.entry_title,
            "mod_type":    self.mod_type,
            "serial":      self.serial,
            "text":        self.text,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NoteEntry":
        return cls(
            id          = d.get("id", str(uuid.uuid4())),
            entry_id    = d.get("entry_id", ""),
            entry_title = d.get("entry_title", ""),
            mod_type    = d.get("mod_type", "other"),
            serial      = d.get("serial", ""),
            text        = d.get("text", ""),
            created_at  = d.get("created_at", ""),
            updated_at  = d.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def get_notes_file(config=None) -> Path:
    """Return the absolute path to the notes JSON file.

    The file is stored next to the application executable alongside other
    persistent data files (``download_history.json``, ``backups/``, etc.).

    Parameters
    ----------
    config:
        Not used for path resolution; kept for API symmetry with sibling
        modules.
    """
    from src.core.config_manager import get_exe_dir
    return Path(get_exe_dir()) / NOTES_FILENAME


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load(config=None) -> List[NoteEntry]:
    """Load all notes from disk.  Returns an empty list on any error."""
    path = get_notes_file(config)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return [NoteEntry.from_dict(d) for d in raw if isinstance(d, dict)]
    except Exception:
        return []


def _save(notes: List[NoteEntry], config=None) -> None:
    """Persist *notes* to disk."""
    path = get_notes_file(config)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([n.to_dict() for n in notes], fh, indent=2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upsert_note(
    config,
    entry_id:    str,
    entry_title: str,
    mod_type:    str,
    serial:      str = "",
    text:        str = "",
) -> NoteEntry:
    """Create a new note or update the existing note for *entry_id*.

    If a note already exists for *entry_id* its *text*, *entry_title*,
    *mod_type*, *serial* and *updated_at* fields are refreshed.  Otherwise a
    brand-new :class:`NoteEntry` is created.

    Parameters
    ----------
    config:
        Application configuration (used to locate the notes file).
    entry_id:
        Stable key for the catalogue entry.
    entry_title:
        Human-readable name of the entry.
    mod_type:
        Category string.
    serial:
        PS2 disc serial (optional).
    text:
        Note body text.

    Returns
    -------
    NoteEntry
        The created or updated note.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")
    notes = _load(config)
    existing = next((n for n in notes if n.entry_id == entry_id), None)

    if existing is not None:
        existing.entry_title = entry_title
        existing.mod_type    = mod_type
        existing.serial      = serial
        existing.text        = text
        existing.updated_at  = now
        _save(notes, config)
        return existing

    note = NoteEntry(
        id          = str(uuid.uuid4()),
        entry_id    = entry_id,
        entry_title = entry_title,
        mod_type    = mod_type,
        serial      = serial,
        text        = text,
        created_at  = now,
        updated_at  = now,
    )
    notes.append(note)
    _save(notes, config)
    return note


def get_note(config, entry_id: str) -> Optional[NoteEntry]:
    """Return the note for *entry_id*, or ``None`` if no note exists.

    Parameters
    ----------
    config:
        Application configuration.
    entry_id:
        Stable identifier for the catalogue entry.
    """
    notes = _load(config)
    return next((n for n in notes if n.entry_id == entry_id), None)


def list_notes(
    config,
    mod_type: Optional[str] = None,
    serial:   Optional[str] = None,
    query:    Optional[str] = None,
) -> List[NoteEntry]:
    """Return all notes, optionally filtered.

    Parameters
    ----------
    config:
        Application configuration.
    mod_type:
        If given, only notes of this mod type are returned.
    serial:
        If given, only notes for this disc serial are returned.
    query:
        If given, only notes whose *entry_title* or *text* contain
        *query* (case-insensitive) are returned.

    Returns
    -------
    list[NoteEntry]
        Matching notes sorted by *updated_at* descending (most recent
        first).  An empty list is returned when the notes file does not
        exist yet.
    """
    notes = _load(config)
    if mod_type:
        notes = [n for n in notes if n.mod_type == mod_type]
    if serial:
        notes = [n for n in notes if n.serial == serial]
    if query:
        q = query.lower()
        notes = [
            n for n in notes
            if q in n.entry_title.lower() or q in n.text.lower()
        ]
    # Sort by updated_at descending (most recently modified first).
    notes.sort(key=lambda n: n.updated_at, reverse=True)
    return notes


def delete_note(config, entry_id: str) -> bool:
    """Remove the note for *entry_id* from disk.

    Parameters
    ----------
    config:
        Application configuration.
    entry_id:
        Stable identifier for the catalogue entry whose note should be
        removed.

    Returns
    -------
    bool
        ``True`` if a note was found and deleted; ``False`` otherwise.
    """
    notes = _load(config)
    new_notes = [n for n in notes if n.entry_id != entry_id]
    if len(new_notes) == len(notes):
        return False
    _save(new_notes, config)
    return True


def clear_notes(config) -> int:
    """Delete all notes from disk.

    Returns
    -------
    int
        The number of notes that were removed.
    """
    notes = _load(config)
    count = len(notes)
    _save([], config)
    return count


def export_notes_csv(config, path: Optional[str] = None) -> str:
    """Export all notes to a CSV file.

    Parameters
    ----------
    config:
        Application configuration.
    path:
        Destination file path.  Defaults to ``mod_notes.csv`` placed
        next to the application executable.

    Returns
    -------
    str
        Absolute path of the written CSV file.
    """
    from src.core.config_manager import get_exe_dir

    if not path:
        path = str(Path(get_exe_dir()) / "mod_notes.csv")

    notes = list_notes(config)
    fieldnames = [
        "id", "entry_id", "entry_title", "mod_type",
        "serial", "text", "created_at", "updated_at",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for n in notes:
            writer.writerow(n.to_dict())

    return path
