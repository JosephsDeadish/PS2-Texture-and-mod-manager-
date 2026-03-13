"""PS2 game serial validator — cross-checks catalogue entries against the
authoritative serial database and reports discrepancies.

The serial database (``data/game_serial_db/ps2_ntsc_u.json``) contains a
curated mapping of game title → primary serial built from majority-vote across
the four catalogue files, with CRC-backed overrides from ``pnach_db/
known_addresses.json`` wherever the vote majority conflicted with CRC evidence.

Usage::

    from src.core.serial_validator import SerialDatabase

    sdb = SerialDatabase()

    # Look up the canonical serial for a game
    serial = sdb.get_serial("Kingdom Hearts")          # "SLUS-20370"

    # Check whether a (game, serial) pair is valid
    ok = sdb.is_valid("Kingdom Hearts", "SLUS-20370")  # True
    ok = sdb.is_valid("Kingdom Hearts", "SLUS-20773")  # False (alt / legacy)

    # Get a full report across one catalogue list
    report = sdb.validate_catalogue(my_list)           # list[ValidationIssue]

    # Cross-check all four catalogues at once
    issues = sdb.validate_all_catalogues()
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


_REPO_ROOT = Path(__file__).parent.parent.parent
_DB_FILE   = _REPO_ROOT / "data" / "game_serial_db" / "ps2_ntsc_u.json"
_CAT_DIR   = _REPO_ROOT / "data" / "catalogue"

_SERIAL_RE = re.compile(r'^[A-Z]{4}-\d{5}$')


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class GameInfo:
    """Information stored for a single game in the serial database."""
    title: str
    serial: str
    alt_serials: List[str] = field(default_factory=list)
    crcs: List[str] = field(default_factory=list)

    def all_serials(self) -> Set[str]:
        """Return the primary serial plus all known alt serials."""
        return {self.serial} | set(self.alt_serials)


@dataclass
class ValidationIssue:
    """A discrepancy found while validating a catalogue entry."""
    source_file: str
    game: str
    serial_found: str
    expected_serial: str
    alt_serials: List[str]
    entry_index: int

    def __str__(self) -> str:
        return (
            f"{self.source_file}[{self.entry_index}] '{self.game}': "
            f"found {self.serial_found!r}, expected {self.expected_serial!r} "
            f"(alts: {self.alt_serials})"
        )


# ---------------------------------------------------------------------------
# SerialDatabase
# ---------------------------------------------------------------------------

class SerialDatabase:
    """Authoritative PS2 game serial database with catalogue validation.

    Parameters
    ----------
    db_path:
        Override the default path to ``ps2_ntsc_u.json`` (useful in tests).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = Path(db_path) if db_path else _DB_FILE
        self._games: Dict[str, GameInfo] = {}
        self._serial_to_titles: Dict[str, List[str]] = {}  # serial → game titles
        self._load()

    # ------------------------------------------------------------------
    # Loading / reloading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the database from disk."""
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        games = raw.get("games", {})
        self._games = {}
        self._serial_to_titles = {}
        for title, info in games.items():
            gi = GameInfo(
                title=title,
                serial=info.get("serial", ""),
                alt_serials=info.get("alt_serials", []),
                crcs=info.get("crcs", []),
            )
            self._games[title] = gi
            for s in gi.all_serials():
                self._serial_to_titles.setdefault(s, []).append(title)

    def reload(self) -> None:
        """Reload the database from disk (picks up on-disk changes)."""
        self._load()

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_info(self, title: str) -> Optional[GameInfo]:
        """Return the :class:`GameInfo` for *title*, or ``None``."""
        return self._games.get(title)

    def get_serial(self, title: str) -> Optional[str]:
        """Return the primary canonical serial for *title*, or ``None``."""
        gi = self._games.get(title)
        return gi.serial if gi else None

    def get_alt_serials(self, title: str) -> List[str]:
        """Return the list of known alt/legacy serials for *title*."""
        gi = self._games.get(title)
        return list(gi.alt_serials) if gi else []

    def is_valid(self, title: str, serial: str) -> bool:
        """Return ``True`` iff *serial* is the primary serial for *title*.

        Note: alt/legacy serials return ``False`` here — they are known but
        not the preferred canonical value.
        """
        gi = self._games.get(title)
        return bool(gi and gi.serial == serial)

    def is_known(self, title: str, serial: str) -> bool:
        """Return ``True`` if *serial* is any known serial (primary or alt)."""
        gi = self._games.get(title)
        return bool(gi and serial in gi.all_serials())

    def titles_for_serial(self, serial: str) -> List[str]:
        """Return all game titles that list *serial* (primary or alt)."""
        return list(self._serial_to_titles.get(serial, []))

    def all_titles(self) -> List[str]:
        """Return all game titles in the database (sorted)."""
        return sorted(self._games.keys())

    def game_count(self) -> int:
        """Return the total number of games in the database."""
        return len(self._games)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    # Prefixes that indicate a regional release (PAL/JP); these are never
    # considered "wrong" even when the DB primary is an NTSC-U serial.
    _REGIONAL_PREFIXES = ("SCES", "SLES", "SLPS", "SCPS", "SCED", "SLED", "SLPM", "SCPM")

    def _is_regional(self, serial: str) -> bool:
        """Return True for PAL/JP serials that should not be normalised to NTSC-U."""
        return serial.upper().startswith(self._REGIONAL_PREFIXES)

    def validate_catalogue(
        self,
        entries: List[dict],
        source_file: str = "catalogue",
    ) -> List[ValidationIssue]:
        """Validate a list of catalogue entry dicts.

        Each entry is expected to have ``'game'`` and ``'game_serial'`` keys.
        Returns a list of :class:`ValidationIssue` for every entry whose serial
        does not match the primary serial in the database.

        Regional (PAL/JP) serials are silently skipped — they are intentional
        choices for region-specific saves or texture packs.
        """
        issues: List[ValidationIssue] = []
        for idx, entry in enumerate(entries):
            title  = (entry.get("game") or "").strip()
            serial = (entry.get("game_serial") or "").strip()
            if not title or not serial:
                continue
            if not _SERIAL_RE.match(serial):
                continue
            # Never treat regional (PAL/JP) serials as wrong
            if self._is_regional(serial):
                continue
            gi = self._games.get(title)
            if gi is None:
                continue  # game not in DB — no opinion
            if serial != gi.serial:
                issues.append(ValidationIssue(
                    source_file=source_file,
                    game=title,
                    serial_found=serial,
                    expected_serial=gi.serial,
                    alt_serials=gi.alt_serials,
                    entry_index=idx,
                ))
        return issues

    def validate_all_catalogues(self) -> List[ValidationIssue]:
        """Validate all four standard catalogue files and return combined issues."""
        catalogues = [
            ("texture_packs.json", _CAT_DIR / "texture_packs.json"),
            ("saves.json",         _CAT_DIR / "saves.json"),
            ("cover_art.json",     _CAT_DIR / "cover_art.json"),
            ("pnach.json",         _CAT_DIR / "pnach.json"),
        ]
        issues: List[ValidationIssue] = []
        for name, path in catalogues:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            issues.extend(self.validate_catalogue(data, source_file=name))
        return issues

    def summary_report(self) -> dict:
        """Return a structured validation summary for all four catalogues.

        Returns a dict with keys:

        - ``total_games_in_db`` — number of games in the serial database
        - ``issues`` — list of issue dicts (game, file, found, expected)
        - ``issue_count`` — total number of issues found
        - ``games_with_issues`` — sorted list of game titles with issues
        """
        issues = self.validate_all_catalogues()
        return {
            "total_games_in_db": self.game_count(),
            "issue_count": len(issues),
            "games_with_issues": sorted({i.game for i in issues}),
            "issues": [
                {
                    "file": i.source_file,
                    "game": i.game,
                    "found": i.serial_found,
                    "expected": i.expected_serial,
                    "entry_index": i.entry_index,
                }
                for i in issues
            ],
        }
