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
from typing import Dict, List, Optional, Set, Tuple


_REPO_ROOT    = Path(__file__).parent.parent.parent
_DB_FILE      = _REPO_ROOT / "data" / "game_serial_db" / "ps2_ntsc_u.json"
_PAL_DB_FILE  = _REPO_ROOT / "data" / "game_serial_db" / "ps2_pal.json"
_DEMO_DB_FILE = _REPO_ROOT / "data" / "game_serial_db" / "ps2_demos.json"
_CAT_DIR      = _REPO_ROOT / "data" / "catalogue"

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
    # Optional metadata sourced from PS2.data.json (NTSC-U region entries).
    # release_date: ISO-8601 date string (e.g. "2001-07-09" or "2001").
    # developer / publisher: studio name (comma-joined when multiple).
    # genre: genre label (comma-joined when multiple).
    release_date: Optional[str] = None
    developer: Optional[str] = None
    publisher: Optional[str] = None
    genre: Optional[str] = None
    # Maps each CRC to a human-readable version label such as "v1.00",
    # "Greatest Hits", "Disc 2", etc.  Only populated for games where
    # specific version information is known; absent keys mean unknown.
    crc_labels: Dict[str, str] = field(default_factory=dict)
    # Human-readable search aliases: common abbreviations (e.g. "DMC", "GoW"),
    # regional alternative titles (e.g. "Dark Chronicle" for Dark Cloud 2),
    # and series shorthand (e.g. "GTA III" for Grand Theft Auto III).
    # The title itself is implicitly searchable; aliases extend coverage.
    aliases: List[str] = field(default_factory=list)
    # Pre-computed lowercase aliases for fast case-insensitive substring search.
    # Populated automatically by SerialDatabase._load(); not stored in JSON.
    _aliases_lower: List[str] = field(default_factory=list, compare=False, repr=False)
    # Disc classification: "retail" for commercial releases, "demo" for demo/
    # promo discs (SCCD/SLCD, SCED/SLED, SCPD/SLPD, etc.), "kiosk" for store
    # kiosk discs.  Sourced from ps2_demos.json; retail DBs default to "retail".
    disc_type: str = "retail"

    def all_serials(self) -> Set[str]:
        """Return the primary serial plus all known alt serials."""
        return {self.serial} | set(self.alt_serials)

    @property
    def region(self) -> str:
        """Return the region derived from the primary serial prefix.

        Returns one of ``"NTSC-U"``, ``"PAL"``, ``"NTSC-J"``, ``"NTSC-K"``,
        ``"Asia"``, or ``""`` when the prefix is not recognised.

        Examples::

            GameInfo(serial="SLUS-20062", ...).region  # "NTSC-U"
            GameInfo(serial="SLES-50000", ...).region  # "PAL"
            GameInfo(serial="SLPS-25000", ...).region  # "NTSC-J"
        """
        from src.core.game_registry import serial_to_region  # local import avoids circular dep
        return serial_to_region(self.serial)


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
    pal_db_path:
        Override the default path to ``ps2_pal.json`` (useful in tests).
    demo_db_path:
        Override the default path to ``ps2_demos.json`` (useful in tests).
        Demo entries are loaded with ``disc_type`` set to the value stored in
        the JSON (``"demo"`` or ``"kiosk"``), keeping them separated from
        retail game entries in all lookup results.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        pal_db_path: Optional[Path] = None,
        demo_db_path: Optional[Path] = None,
    ) -> None:
        self._path      = Path(db_path)      if db_path      else _DB_FILE
        self._pal_path  = Path(pal_db_path)  if pal_db_path  else _PAL_DB_FILE
        self._demo_path = Path(demo_db_path) if demo_db_path else _DEMO_DB_FILE
        self._games: Dict[str, GameInfo] = {}
        self._serial_to_titles: Dict[str, List[str]] = {}  # serial → game titles
        self._crc_to_title: Dict[str, str] = {}            # CRC (upper) → game title
        self._alias_to_titles: Dict[str, List[str]] = {}   # alias lower → game titles
        self._demo_serials: Set[str] = set()               # serials that belong to demo/kiosk discs
        self._load()

    # ------------------------------------------------------------------
    # Loading / reloading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the NTSC-U, PAL, and demo databases from disk.

        ``ps2_ntsc_u.json`` and ``ps2_pal.json`` are loaded first (retail
        entries, ``disc_type="retail"``).  ``ps2_demos.json`` is loaded last
        with each entry's ``disc_type`` taken directly from the JSON (defaults
        to ``"demo"``).  Demo titles carry a ``(Demo)`` or similar suffix in
        the JSON so there are no duplicate keys with retail entries.
        Serial-to-title and CRC-to-title indices merge transparently across
        all three files; ``_demo_serials`` is rebuilt on every load for fast
        ``is_demo_serial()`` queries.
        """
        self._games = {}
        self._serial_to_titles = {}
        self._crc_to_title = {}
        self._alias_to_titles = {}
        self._demo_serials = set()
        # Retail databases first, then demos
        retail_paths = (self._path, self._pal_path)
        for path in retail_paths:
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for title, info in raw.get("games", {}).items():
                gi = GameInfo(
                    title=title,
                    serial=info.get("serial", ""),
                    alt_serials=info.get("alt_serials", []),
                    crcs=info.get("crcs", []),
                    release_date=info.get("release_date") or None,
                    developer=info.get("developer") or None,
                    publisher=info.get("publisher") or None,
                    genre=info.get("genre") or None,
                    crc_labels=info.get("crc_labels") or {},
                    aliases=info.get("aliases") or [],
                    disc_type="retail",
                )
                gi._aliases_lower = [a.lower() for a in gi.aliases]
                self._games[title] = gi
                for s in gi.all_serials():
                    self._serial_to_titles.setdefault(s, []).append(title)
                for crc in gi.crcs:
                    self._crc_to_title[crc.upper()] = title
                for alias in gi.aliases:
                    self._alias_to_titles.setdefault(alias.lower(), []).append(title)
        # Demo / kiosk / promo database
        if self._demo_path.is_file():
            try:
                raw = json.loads(self._demo_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
            for title, info in raw.get("games", {}).items():
                disc_type = info.get("disc_type") or "demo"
                gi = GameInfo(
                    title=title,
                    serial=info.get("serial", ""),
                    alt_serials=info.get("alt_serials", []),
                    crcs=info.get("crcs", []),
                    release_date=info.get("release_date") or None,
                    developer=info.get("developer") or None,
                    publisher=info.get("publisher") or None,
                    genre=info.get("genre") or None,
                    crc_labels=info.get("crc_labels") or {},
                    aliases=info.get("aliases") or [],
                    disc_type=disc_type,
                )
                gi._aliases_lower = [a.lower() for a in gi.aliases]
                self._games[title] = gi
                for s in gi.all_serials():
                    self._serial_to_titles.setdefault(s, []).append(title)
                    self._demo_serials.add(s)
                for crc in gi.crcs:
                    self._crc_to_title[crc.upper()] = title
                for alias in gi.aliases:
                    self._alias_to_titles.setdefault(alias.lower(), []).append(title)

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

    def info_for_serial(self, serial: str) -> Optional[GameInfo]:
        """Return the :class:`GameInfo` for the game that owns *serial*, or ``None``.

        Both primary and alt serials are searched.  When multiple titles share
        *serial* (rare edge-case), the first match is returned.

        Examples::

            sdb.info_for_serial("SLUS-20062")  # GameInfo for "Spyro: Enter the Dragonfly"
            sdb.info_for_serial("SCUS-97113")  # GameInfo for "Ico"
        """
        titles = self._serial_to_titles.get(serial.upper() if serial else "", [])
        for title in titles:
            gi = self._games.get(title)
            if gi:
                return gi
        return None

    def crcs_for_serial(self, serial: str) -> List[str]:
        """Return the list of known CRCs for the game that owns *serial*.

        Both primary and alt serials are searched.  Returns an empty list when
        the serial is not in the database or has no CRCs recorded.

        Examples::

            sdb.crcs_for_serial("SCUS-97399")
            # ["17D68D15", "F0A34C75"]  (God of War original + Greatest Hits)

            sdb.crcs_for_serial("SLUS-99999")
            # []  (unknown serial)
        """
        gi = self.info_for_serial(serial)
        return list(gi.crcs) if gi else []

    def all_titles(self) -> List[str]:
        """Return all game titles in the database (sorted)."""
        return sorted(self._games.keys())

    def game_count(self) -> int:
        """Return the total number of games in the database."""
        return len(self._games)

    def aliases_for_title(self, title: str) -> List[str]:
        """Return the list of search aliases for *title* (empty if none)."""
        gi = self._games.get(title)
        return list(gi.aliases) if gi else []

    def search_titles(self, query: str) -> List[str]:
        """Return all game titles whose title *or* any alias contains *query*.

        The match is a case-insensitive substring check against the canonical
        title and every alias stored for that game.  Useful for resolving
        abbreviations (e.g. "GoW" → ["God of War"]) and regional variant
        names (e.g. "Dark Chronicle" → ["Dark Cloud 2"]).

        Examples::

            sdb.search_titles("GoW")           # ["God of War", "God of War II", ...]
            sdb.search_titles("dark chronicle") # ["Dark Cloud 2"]
            sdb.search_titles("gta iii")        # ["Grand Theft Auto III"]
        """
        q = query.strip().lower()
        if not q:
            return []
        seen: set = set()
        results: List[str] = []
        for title, gi in self._games.items():
            if title in seen:
                continue
            if q in title.lower() or any(q in a for a in gi._aliases_lower):
                results.append(title)
                seen.add(title)
        return sorted(results)

    def title_matches_query(self, game_title: str, query: str) -> bool:
        """Return ``True`` if *query* matches *game_title* or any of its aliases.

        Used by search/filter UIs so that a user can type an abbreviation
        (e.g. ``"DMC3"``) and still find an entry whose ``game`` field contains
        the full canonical name (``"Devil May Cry 3: Dante's Awakening"``).

        The match is a case-insensitive substring check::

            sdb.title_matches_query("Devil May Cry 3: Dante's Awakening", "DMC3")
            # True — "DMC3" is an alias for that title

            sdb.title_matches_query("Devil May Cry 3: Dante's Awakening", "Dante")
            # True — "Dante" appears in the title itself
        """
        q = query.strip().lower()
        if not q:
            return True
        if q in game_title.lower():
            return True
        gi = self._games.get(game_title)
        if gi:
            return any(q in a for a in gi._aliases_lower)
        return False

    def serial_for_crc(self, crc: str) -> Optional[str]:
        """Return the primary serial for the game that owns *crc*, or ``None``.

        The lookup is CRC-indexed for O(1) performance.
        """
        title = self._crc_to_title.get(crc.upper().strip())
        if title is None:
            return None
        gi = self._games.get(title)
        return gi.serial if gi else None

    def label_for_crc(self, crc: str) -> Optional[str]:
        """Return the human-readable version label for *crc*, or ``None``.

        Version labels are stored in the ``crc_labels`` dict inside each game
        entry (e.g. ``"v1.00"``, ``"Greatest Hits"``, ``"Disc 2"``).  When no
        label has been recorded for a CRC the method returns ``None`` so that
        callers can decide how to display "unknown version" themselves.

        Examples::

            db.label_for_crc("17D68D15")   # "v1.00" (God of War original)
            db.label_for_crc("F0A34C75")   # "Greatest Hits" (God of War GH)
            db.label_for_crc("99999999")   # None (not in DB)
        """
        crc_upper = crc.upper().strip()
        title = self._crc_to_title.get(crc_upper)
        if title is None:
            return None
        gi = self._games.get(title)
        if gi is None:
            return None
        return gi.crc_labels.get(crc_upper) or None

    def all_crcs_for_title(self, title: str) -> List[Tuple[str, Optional[str]]]:
        """Return all ``(CRC, version_label)`` pairs for *title*.

        The version label is ``None`` when no label has been recorded for that
        CRC.  The pairs are ordered the same way as the ``crcs`` list in the
        database.

        Example::

            db.all_crcs_for_title("God of War")
            # [("17D68D15", "v1.00"), ("F0A34C75", "Greatest Hits"), ...]
        """
        gi = self._games.get(title)
        if gi is None:
            return []
        return [
            (crc, gi.crc_labels.get(crc.upper()) or None)
            for crc in gi.crcs
        ]

    def is_demo_serial(self, serial: str) -> bool:
        """Return ``True`` if *serial* belongs to a demo, kiosk, or promo disc.

        Checks the ``_demo_serials`` index built from ``ps2_demos.json``.
        Returns ``False`` for retail serials and for serials not present in
        any loaded database.

        Examples::

            sdb.is_demo_serial("SLUS-29001")  # True  — MGS2 demo
            sdb.is_demo_serial("SLUS-20210")  # False — retail Metal Gear Solid 2
        """
        return serial in self._demo_serials

    def demo_titles(self) -> List[str]:
        """Return all demo/kiosk/promo titles loaded from ``ps2_demos.json`` (sorted).

        Retail titles are excluded.  Useful for populating a dedicated demo
        browser in the UI.

        Example::

            sdb.demo_titles()
            # ["Dark Cloud (Demo)", "Final Fantasy X (Demo)", ...]
        """
        return sorted(
            title for title, gi in self._games.items()
            if gi.disc_type in ("demo", "kiosk", "promo")
        )

    def retail_titles(self) -> List[str]:
        """Return all retail game titles (sorted), excluding demos and kiosk discs.

        Example::

            sdb.retail_titles()
            # ["007: Agent Under Fire", ".hack//G.U. Vol.1//Rebirth", ...]
        """
        return sorted(
            title for title, gi in self._games.items()
            if gi.disc_type == "retail"
        )

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

    # ------------------------------------------------------------------
    # CRC ↔ Serial cross-validation
    # ------------------------------------------------------------------

    def validate_crc_serial_consistency(
        self,
        pnach_db_path: Optional[Path] = None,
    ) -> List[dict]:
        """Cross-check every CRC entry in the PNACH DB against the serial DB.

        For each CRC entry that carries a ``game_serial`` value, verify that:

        1. The serial exists as a primary **or** alt serial in the serial DB
           (both NTSC-U and PAL databases are checked).
        2. The serial matches the format ``XXXX-NNNNN``.

        Returns a list of issue dicts with keys:

        - ``crc``         — the 8-hex-digit CRC string
        - ``game``        — game name from the PNACH DB entry
        - ``serial``      — the serial found in the PNACH DB entry
        - ``issue``       — human-readable description of the problem
        """
        pnach_path = Path(pnach_db_path) if pnach_db_path else (
            _REPO_ROOT / "data" / "pnach_db" / "known_addresses.json"
        )
        if not pnach_path.is_file():
            return []
        try:
            pnach_db = json.loads(pnach_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        issues: List[dict] = []
        seen: set = set()  # (crc, serial) — avoid duplicate reports per CRC

        for key, val in pnach_db.items():
            crc    = key.split(":")[0]
            serial = (val.get("game_serial") or "").strip()
            game   = (val.get("game") or "").strip()
            if not serial:
                continue
            pair = (crc, serial)
            if pair in seen:
                continue
            seen.add(pair)

            # Format check
            if not _SERIAL_RE.match(serial):
                issues.append({
                    "crc": crc, "game": game, "serial": serial,
                    "issue": f"serial {serial!r} does not match XXXX-NNNNN format",
                })
                continue

            # Existence check — serial must be known in the DB
            titles = self.titles_for_serial(serial)
            if not titles:
                issues.append({
                    "crc": crc, "game": game, "serial": serial,
                    "issue": (
                        f"serial {serial!r} not found in serial DB "
                        f"(neither primary nor alt for any title)"
                    ),
                })

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
