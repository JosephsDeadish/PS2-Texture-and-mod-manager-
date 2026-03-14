"""Texture Hash Database for PS2 Mod Manager.

Stores SHA-256 hashes of texture files so that the manager can:

* **Detect duplicates** — two texture files with identical content.
* **Detect overwritten textures** — a pack installs a file whose hash
  matches a file already installed by another pack.
* **Detect mod conflicts** — two packs provide replacements for the same
  PCSX2 texture filename, which means only one can be active at a time.
* **Detect broken textures** — zero-byte or impossibly small files.
* **Enable community texture libraries** — share a catalogue of known
  hashes so users can identify textures by their SHA-256 fingerprint.

Terminology
-----------
texture_id:
    The PCSX2 replacement filename (e.g.
    ``abc12345-3b0f5ac99a2574db-00006653.png``).  This is PCSX2's
    "hash-based filename" — the key used for replacement matching.
    Two files with the same ``texture_id`` compete for the same slot in
    PCSX2's texture replacement system.
content_hash:
    A SHA-256 hex-digest of the file's raw bytes.  Used to detect
    duplicate content regardless of filename.
pack_id:
    An identifier for the source mod / texture pack (typically the mod
    UUID or folder name).

Public API::

    from src.core.texture_hash_db import TextureHashDB, TextureEntry

    db = TextureHashDB("/path/to/hash_db.json")
    db.register_pack("my-pack-uuid", "/textures/SLUS-20062/replacements/")
    dupes = db.find_duplicates()
    conflicts = db.find_overwrite_conflicts()
    db.save()
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum plausible size for a valid PS2 replacement texture (bytes).
#: Files smaller than this are flagged as potentially broken.
MIN_TEXTURE_BYTES: int = 64

#: Image file extensions recognised as textures.
TEXTURE_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".dds", ".bmp", ".tga", ".jpg", ".jpeg",
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TextureEntry:
    """One texture file tracked by the hash database.

    Attributes
    ----------
    texture_id:
        PCSX2 replacement filename (the filename PCSX2 uses to match the
        replacement to the original dumped texture).
    pack_id:
        Identifier of the mod / texture pack that owns this file.
    file_path:
        Absolute path to the texture file on disk.
    content_hash:
        SHA-256 hex-digest of the file's raw bytes.
    size_bytes:
        File size in bytes at the time of registration.
    broken:
        ``True`` if the file is zero-length or suspiciously small.
    """

    texture_id: str
    pack_id: str
    file_path: str
    content_hash: str
    size_bytes: int
    broken: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TextureEntry":
        known = {"texture_id", "pack_id", "file_path", "content_hash",
                 "size_bytes", "broken"}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class TextureConflict:
    """Two or more texture entries that share the same ``texture_id``.

    Only one of these can be active in PCSX2 at a time; they represent
    competing replacements for the same original texture.

    Attributes
    ----------
    texture_id:
        The shared PCSX2 replacement filename.
    entries:
        All registered :class:`TextureEntry` objects with this id.
    is_duplicate_content:
        ``True`` when all competing entries have identical
        ``content_hash`` values (same image, different packs).
    """

    texture_id: str
    entries: List[TextureEntry] = field(default_factory=list)
    is_duplicate_content: bool = False

    @property
    def pack_ids(self) -> List[str]:
        """Return the pack IDs involved in this conflict."""
        return [e.pack_id for e in self.entries]


# ---------------------------------------------------------------------------
# Core database class
# ---------------------------------------------------------------------------

class TextureHashDB:
    """Hash-indexed database of texture files across installed packs.

    Parameters
    ----------
    db_path:
        Path to the JSON file used for persistence.  The file is
        created on first :meth:`save`.
    """

    _VERSION = 1

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        #: texture_id → list[TextureEntry]
        self._by_texture_id: Dict[str, List[TextureEntry]] = {}
        #: content_hash → list[TextureEntry]
        self._by_hash: Dict[str, List[TextureEntry]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load existing entries from *db_path* if the file exists."""
        if not self._db_path.exists():
            return
        try:
            raw = json.loads(self._db_path.read_text(encoding="utf-8"))
            for rec in raw.get("entries", []):
                entry = TextureEntry.from_dict(rec)
                self._index(entry)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # corrupt DB — start fresh

    def save(self) -> None:
        """Persist all entries to disk atomically."""
        entries = [
            e.to_dict()
            for lst in self._by_texture_id.values()
            for e in lst
        ]
        payload = {
            "version": self._VERSION,
            "entries": entries,
        }
        data = json.dumps(payload, indent=2)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._db_path.parent),
            prefix=".texhash_tmp_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, str(self._db_path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index(self, entry: TextureEntry) -> None:
        self._by_texture_id.setdefault(entry.texture_id, []).append(entry)
        self._by_hash.setdefault(entry.content_hash, []).append(entry)

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return the SHA-256 hex-digest of *path*."""
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _is_texture_file(path: Path) -> bool:
        return path.suffix.lower() in TEXTURE_EXTENSIONS

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_file(
        self,
        texture_id: str,
        pack_id: str,
        file_path: str,
    ) -> TextureEntry:
        """Register one texture file and index it.

        Parameters
        ----------
        texture_id:
            PCSX2 replacement filename (the name PCSX2 expects, usually
            the same as the file's basename).
        pack_id:
            Identifier of the owning texture pack / mod.
        file_path:
            Absolute path to the texture file.

        Returns
        -------
        TextureEntry
            The newly created entry.
        """
        p = Path(file_path)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0

        broken = size < MIN_TEXTURE_BYTES

        if broken or size == 0:
            content_hash = hashlib.sha256(b"").hexdigest()
        else:
            try:
                content_hash = self._hash_file(p)
            except OSError:
                content_hash = hashlib.sha256(b"").hexdigest()
                broken = True

        entry = TextureEntry(
            texture_id=texture_id,
            pack_id=pack_id,
            file_path=str(p),
            content_hash=content_hash,
            size_bytes=size,
            broken=broken,
        )
        self._index(entry)
        return entry

    def register_pack(
        self,
        pack_id: str,
        replacements_dir: str,
    ) -> List[TextureEntry]:
        """Scan *replacements_dir* and register all texture files.

        Each texture file's basename is used as its ``texture_id`` (i.e.
        the filename PCSX2 uses for replacement matching).  This is
        consistent with how PCSX2 resolves texture replacements — it
        matches by filename within the replacements folder.

        Parameters
        ----------
        pack_id:
            Identifier of the texture pack being registered.
        replacements_dir:
            Path to the pack's replacements folder (may contain sub-dirs).

        Returns
        -------
        list[TextureEntry]
            All entries created from this scan.
        """
        root = Path(replacements_dir)
        if not root.is_dir():
            return []

        registered: List[TextureEntry] = []
        try:
            for dirpath, _dirs, filenames in os.walk(root):
                for fname in filenames:
                    p = Path(dirpath) / fname
                    if not self._is_texture_file(p):
                        continue
                    entry = self.register_file(
                        texture_id=fname,   # PCSX2 matches by basename
                        pack_id=pack_id,
                        file_path=str(p),
                    )
                    registered.append(entry)
        except PermissionError:
            pass
        return registered

    def remove_pack(self, pack_id: str) -> int:
        """Remove all entries belonging to *pack_id*.

        Returns
        -------
        int
            Number of entries removed.
        """
        removed = 0
        for tid in list(self._by_texture_id):
            lst = [e for e in self._by_texture_id[tid] if e.pack_id != pack_id]
            removed += len(self._by_texture_id[tid]) - len(lst)
            if lst:
                self._by_texture_id[tid] = lst
            else:
                del self._by_texture_id[tid]

        for h in list(self._by_hash):
            lst = [e for e in self._by_hash[h] if e.pack_id != pack_id]
            if lst:
                self._by_hash[h] = lst
            else:
                del self._by_hash[h]

        return removed

    def clear(self) -> None:
        """Remove all entries from the in-memory database."""
        self._by_texture_id.clear()
        self._by_hash.clear()

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def all_entries(self) -> List[TextureEntry]:
        """Return a flat list of all registered texture entries."""
        return [e for lst in self._by_texture_id.values() for e in lst]

    def entries_for_pack(self, pack_id: str) -> List[TextureEntry]:
        """Return all entries belonging to *pack_id*."""
        return [e for e in self.all_entries() if e.pack_id == pack_id]

    def find_broken_textures(self) -> List[TextureEntry]:
        """Return all entries flagged as broken (zero/very small files)."""
        return [e for e in self.all_entries() if e.broken]

    def find_duplicates(self) -> List[List[TextureEntry]]:
        """Return groups of entries that share identical file content.

        Each group contains two or more entries with the same SHA-256
        hash.  Entries within the same pack are included — duplicate
        content across packs is reported as a potential waste of disk
        space.

        Returns
        -------
        list[list[TextureEntry]]
            Each inner list has ≥ 2 entries with the same content hash.
        """
        groups = []
        for h, lst in self._by_hash.items():
            if len(lst) >= 2:
                groups.append(list(lst))
        return groups

    def find_overwrite_conflicts(self) -> List[TextureConflict]:
        """Return conflicts where two or more packs provide the same texture_id.

        In PCSX2 texture replacement, each ``texture_id`` (filename) can
        only have one active replacement.  If two installed packs provide
        a file with the same name, only one will be used — the other is
        silently ignored.

        Returns
        -------
        list[TextureConflict]
            One entry per ``texture_id`` that is claimed by more than one
            registered pack.
        """
        conflicts: List[TextureConflict] = []
        for tid, lst in self._by_texture_id.items():
            # Only flag when more than one *different* pack is involved
            pack_ids = {e.pack_id for e in lst}
            if len(pack_ids) < 2:
                continue
            hashes = {e.content_hash for e in lst}
            conflicts.append(TextureConflict(
                texture_id=tid,
                entries=list(lst),
                is_duplicate_content=len(hashes) == 1,
            ))
        return sorted(conflicts, key=lambda c: c.texture_id)

    def find_cross_pack_duplicates(self) -> List[List[TextureEntry]]:
        """Return groups of entries from *different* packs with identical content.

        Unlike :meth:`find_duplicates`, this only reports cases where
        distinct packs provide the exact same image bytes.

        Returns
        -------
        list[list[TextureEntry]]
            Each group has entries from at least two different packs with
            the same SHA-256 hash.
        """
        groups = []
        for h, lst in self._by_hash.items():
            pack_ids = {e.pack_id for e in lst}
            if len(pack_ids) >= 2:
                groups.append(list(lst))
        return groups

    def stats(self) -> dict:
        """Return summary statistics for the database.

        Returns
        -------
        dict
            Keys: ``total_entries``, ``total_packs``, ``broken_count``,
            ``duplicate_groups``, ``overwrite_conflicts``.
        """
        all_e = self.all_entries()
        return {
            "total_entries":      len(all_e),
            "total_packs":        len({e.pack_id for e in all_e}),
            "broken_count":       sum(1 for e in all_e if e.broken),
            "duplicate_groups":   len(self.find_duplicates()),
            "overwrite_conflicts": len(self.find_overwrite_conflicts()),
        }
