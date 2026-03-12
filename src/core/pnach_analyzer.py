"""PNACH code analyzer — annotates memory addresses with human-readable descriptions.

This module maintains a database of known PS2 game memory addresses mapped to
functional descriptions.  When a user is resolving PNACH conflicts the UI can
query ``describe_address`` to show plain-English notes like:

    "Jump height multiplier — controls how high the character can jump"

The database is keyed by ``(game_crc_upper, processor_upper, address_upper)``.
Entries are stored in ``data/pnach_db/known_addresses.json`` and can be
extended at any time without code changes.

Additionally :func:`infer_category` provides lightweight heuristic analysis of
a patch's raw value relative to common floating-point and integer constants so
that completely unknown addresses can receive a rough category guess.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_DB_FILE = _REPO_ROOT / "data" / "pnach_db" / "known_addresses.json"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_db() -> Dict[str, dict]:
    """Load the known-address database from disk.  Returns empty dict on error."""
    try:
        if _DB_FILE.is_file():
            return json.loads(_DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


_DB: Dict[str, dict] = _load_db()


def _db_key(game_crc: str, processor: str, address: str) -> str:
    return f"{game_crc.upper()}:{processor.upper()}:{address.upper().zfill(8)}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def describe_address(
    game_crc: str,
    processor: str,
    address: str,
) -> Optional[str]:
    """Return a human-readable description for a known (game, address) pair.

    Returns *None* when no annotation is available.
    """
    key = _db_key(game_crc, processor, address)
    entry = _DB.get(key)
    if entry:
        return entry.get("description", None)
    return None


def describe_patch(
    game_crc: str,
    processor: str,
    address: str,
    value: str,
    size: str = "word",
) -> dict:
    """Return a rich annotation dict for a single patch line.

    Keys:
      ``description``   — human-readable label (str or None)
      ``category``      — inferred category string (e.g. "gameplay", "graphics")
      ``value_note``    — human-readable value interpretation
      ``inferred``      — True if the description was heuristically guessed

    Always returns a complete dict (no keys are absent).
    """
    known = describe_address(game_crc, processor, address)
    key = _db_key(game_crc, processor, address)
    entry = _DB.get(key, {})
    category = entry.get("category", infer_category(address, value, size))
    value_note = _interpret_value(value, size, entry.get("value_map"))
    return {
        "description": known or None,
        "category": category,
        "value_note": value_note,
        "inferred": known is None,
    }


def group_conflicts_by_function(
    conflicts: List[dict],
) -> Dict[str, List[dict]]:
    """Group a list of PNACH conflict dicts by their functional category.

    Input: list of dicts with keys: ``game_crc``, ``processor``, ``address``,
    ``mod_a_id``, ``value_a``, ``mod_b_id``, ``value_b``.

    Returns mapping of ``category`` → list of enriched conflict dicts (each
    gets an extra ``annotation`` key from :func:`describe_patch`).
    """
    groups: Dict[str, List[dict]] = {}
    for c in conflicts:
        ann = describe_patch(
            c.get("game_crc", ""),
            c.get("processor", "EE"),
            c.get("address", ""),
            c.get("value_a", "0"),
        )
        c = dict(c)  # shallow copy, don't mutate caller's dict
        c["annotation"] = ann
        cat = ann["category"]
        groups.setdefault(cat, []).append(c)
    return groups


def infer_category(address: str, value: str, size: str = "word") -> str:
    """Heuristically guess a category for an address/value pair.

    Uses address ranges known from common PS2 EE/IOP memory maps and value
    characteristics to return a category label such as:
        "gameplay", "graphics", "audio", "physics", "ui", "cheat", "unknown"
    """
    try:
        addr_int = int(address, 16)
    except ValueError:
        return "unknown"

    # Very rough EE RDRAM range partitioning based on common patterns seen in
    # PCSX2 PNACH archives.  Addresses in 0x00000000-0x01FFFFFF are standard
    # EE RDRAM; IOP RAM lives at 0x1F800000+.
    if 0x00100000 <= addr_int <= 0x00FFFFFF:
        # Low RDRAM — typically game engine globals: physics, gameplay floats
        return _guess_from_value(value, size, default="physics")
    if 0x01000000 <= addr_int <= 0x01FFFFFF:
        return _guess_from_value(value, size, default="gameplay")
    if 0x00380000 <= addr_int <= 0x003FFFFF:
        return "graphics"
    if 0x10000000 <= addr_int <= 0x1001FFFF:
        return "hardware_registers"

    return _guess_from_value(value, size, default="gameplay")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _guess_from_value(value: str, size: str, default: str = "gameplay") -> str:
    """Classify by value characteristics."""
    try:
        raw = int(value, 16)
    except ValueError:
        return default

    # Floating-point heuristics (IEEE 754 single)
    if size in ("word", "extended"):
        try:
            fval = struct.unpack(">f", struct.pack(">I", raw & 0xFFFFFFFF))[0]
            if 0.01 < abs(fval) < 100.0:
                # Likely a float multiplier/constant — physics or gameplay
                return "physics"
        except (struct.error, OverflowError):
            pass

    # Suspiciously large integers → probably cheat codes (infinite ammo etc.)
    if raw in (0x7FFFFFFF, 0xFFFFFFFF, 0x63, 0x9999, 0x270F):
        return "cheat"

    # Small integers (0-255) typical for boolean flags or counters
    if 0 <= raw <= 0xFF:
        return "gameplay"

    return default


_FLOAT_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def _interpret_value(value: str, size: str, value_map: Optional[dict] = None) -> str:
    """Return a human-readable string describing the patch value."""
    if value_map:
        # Build a normalised lookup (keys → upper-case) to handle mixed-case value maps
        norm_map = {k.upper(): v for k, v in value_map.items()}
        if value.upper() in norm_map:
            return norm_map[value.upper()]

    try:
        raw = int(value, 16)
    except ValueError:
        return f"raw: {value}"

    notes = [f"hex: 0x{raw:X}  dec: {raw}"]

    if size in ("word", "extended") and _FLOAT_RE.match(value):
        try:
            import math as _math
            fval = struct.unpack(">f", struct.pack(">I", raw))[0]
            if not _math.isnan(fval) and abs(fval) < 1e10:
                notes.append(f"float: {fval:.4g}")
        except (struct.error, OverflowError):
            pass

    return "  |  ".join(notes)


# ---------------------------------------------------------------------------
# Code-builder helpers — query DB by game serial/CRC, generate PNACH text
# ---------------------------------------------------------------------------

def entries_for_serial(serial: str) -> List[dict]:
    """Return all DB entries for a game identified by its PS2 serial number.

    The search checks the ``game_serial`` field first, then falls back to
    looking for the serial embedded in the ``game`` description string (the
    convention used when adding entries, e.g. ``"Okami (SLUS-21344)"``).

    Each returned dict is an enriched copy of the DB entry with an additional
    ``key`` field containing the raw DB key (``CRC:PROC:ADDR``).
    """
    serial_upper = serial.strip().upper()
    results: List[dict] = []
    seen_keys: set = set()
    for key, entry in _DB.items():
        if key in seen_keys:
            continue
        # Preferred: explicit game_serial field
        stored_serial = entry.get("game_serial", "")
        if stored_serial and stored_serial.upper() == serial_upper:
            results.append({"key": key, **entry})
            seen_keys.add(key)
            continue
        # Fallback: serial embedded in the game name string
        game = entry.get("game", "")
        if serial_upper in game.upper():
            results.append({"key": key, **entry})
            seen_keys.add(key)
    return results


def entries_for_crc(game_crc: str) -> List[dict]:
    """Return all DB entries for a game identified by its CRC.

    Each returned dict includes the raw DB ``key`` plus all stored fields.
    """
    crc_upper = game_crc.strip().upper()
    results: List[dict] = []
    for key, entry in _DB.items():
        if entry.get("game_crc", "").upper() == crc_upper:
            results.append({"key": key, **entry})
    return results


def generate_pnach_text(
    game_crc: str,
    game_title: str,
    patches: List[dict],
    comment: str = "Generated by PS2 Mod Manager Code Builder",
) -> str:
    """Generate valid PNACH file content from a list of patch dicts.

    Each dict in *patches* must contain:
      * ``processor``  — e.g. ``"EE"`` (default) or ``"IOP"``
      * ``address``    — 8 hex-digit address string
      * ``value``      — 8 hex-digit value string
      * ``description``— optional human-readable label (emitted as a comment)
      * ``size``       — optional size keyword (default ``"extended"``)

    The returned string is ready to be written to ``<CRC>.pnach``.
    """
    lines = [
        f"gametitle={game_title}",
        f"comment={comment}",
        "",
    ]
    for p in patches:
        desc = (p.get("description") or "").strip()
        if desc:
            lines.append(f"// {desc}")
        proc = p.get("processor", "EE").upper()
        addr = p.get("address", "00000000").upper().zfill(8)
        size = p.get("size", "extended")
        value = p.get("value", "00000000").upper().zfill(8)
        lines.append(f"patch=1,{proc},{addr},{size},{value}")
    return "\n".join(lines) + "\n"


def list_all_serials_in_db() -> List[Tuple[str, str]]:
    """Return a sorted list of ``(serial, game_title)`` pairs found in the DB.

    Used by the Code Builder game picker to populate its dropdown.
    """
    seen: Dict[str, str] = {}
    for entry in _DB.values():
        serial = entry.get("game_serial", "")
        game = entry.get("game", "")
        if not serial:
            # Try to extract serial from embedded game string like "Title (SLUS-21028)"
            import re as _re
            m = _re.search(r'\((S[LC]US-\d{5}|SCES-\d{5}|SLES-\d{5}|SLPS-\d{5})\)', game)
            if m:
                serial = m.group(1)
        if serial and serial not in seen:
            # Strip the "(SERIAL)" suffix from the game title if present
            title = game.split(" (")[0] if " (" in game else game
            seen[serial] = title
    return sorted(seen.items(), key=lambda x: x[1])


# ---------------------------------------------------------------------------
# DB refresh (used by tests / tooling)
# ---------------------------------------------------------------------------

def reload_db() -> int:
    """Reload the address database from disk.  Returns entry count."""
    global _DB
    _DB = _load_db()
    return len(_DB)
