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


def check_exclusion_conflicts(
    selected_entries: List[dict],
) -> List[dict]:
    """Check a list of selected DB entries for *exclusion group* conflicts.

    Entries that share the same non-empty ``exclusion_group`` field are
    mutually exclusive — only one may be active at a time.  A typical example
    is a set of attack-damage multipliers for a fighting game: the user should
    pick *one* level (2×, 5×, max) rather than stacking them.

    Note that entries with *different* exclusion groups (or no group at all)
    are allowed together even if they appear related.  For example a
    "Ki blast visual size" entry (no exclusion group) does **not** conflict
    with a "Ki blast damage multiplier" entry (in group ``ki_damage_*``).

    Parameters
    ----------
    selected_entries:
        List of entry dicts, each expected to have at least a ``description``
        key and optionally ``exclusion_group`` and ``exclusion_note`` keys.
        (Pass only the *checked/enabled* entries.)

    Returns
    -------
    A list of conflict dicts.  Each dict has:
    ``group``       — the exclusion group identifier string
    ``entries``     — list of (description, exclusion_note) pairs that clash
    ``message``     — human-readable conflict summary
    """
    seen: Dict[str, List[dict]] = {}
    for entry in selected_entries:
        grp = entry.get("exclusion_group", "").strip()
        if not grp:
            continue
        seen.setdefault(grp, []).append(entry)

    conflicts = []
    for grp, entries in seen.items():
        if len(entries) < 2:
            continue
        descs = [e.get("description", "?") for e in entries]
        note = entries[0].get("exclusion_note", "")
        if not note:
            note = (
                "These effects modify the same game value and cannot be "
                "combined. Disable all but one."
            )
        msg = (
            f"⚡ Incompatible options selected ({grp}):\n"
            + "\n".join(f"  • {d}" for d in descs)
            + f"\n{note}"
        )
        conflicts.append({"group": grp, "entries": descs, "message": msg})
    return conflicts


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


# ---------------------------------------------------------------------------
# SCE pad / input compatibility API
# ---------------------------------------------------------------------------

#: Valid ``input_compat`` values and their human-readable meanings.
INPUT_COMPAT_LABELS: Dict[str, str] = {
    "standard_sce_pad": "✅ Standard SCE libpad — button bitmasks and PNACH writes are valid",
    "inverted_sce_pad": "⚠ Inverted SCE pad — bitmask bits are pressed=0; values must be inverted",
    "analog_only":      "❌ Analog-only input — game reads axes not digital flags; combo writes have no effect",
    "custom_polling":   "⚠ Custom polling — game uses proprietary input loop; standard bitmask may not apply",
    "not_applicable":   "ℹ Not applicable — this entry does not involve controller input",
    "unknown":          "⚠ Unknown compatibility — verify address in PCSX2 Debug → Memory Search first",
}

#: Description of the SCE pad bitmask standard for display in tooltips.
SCE_PAD_BITMASK_DESCRIPTION = (
    "PS2 SCE libpad standard button bitmask (pressed = bit set to 1 in game's normalized copy):\n"
    "  0x0001 Select  |  0x0002 L3  |  0x0004 R3   |  0x0008 Start\n"
    "  0x0010 D-Up    |  0x0020 D-R |  0x0040 D-Dn |  0x0080 D-Left\n"
    "  0x0100 L2      |  0x0200 R2  |  0x0400 L1   |  0x0800 R1\n"
    "  0x1000 △       |  0x2000 ○   |  0x4000 ✕    |  0x8000 □\n\n"
    "Note: raw scePadRead uses inverted convention (pressed=0).  Most games\n"
    "normalize this before storing in their own pad-state struct (pressed=1).\n"
    "PNACH codes target the game's normalized copy, not the raw DMA buffer."
)

#: Why some games' PNACH codes may not work — informational text for the UI.
SCE_PAD_INCOMPATIBILITY_REASONS = (
    "Reasons a freecam PNACH may not work in some games:\n"
    "  • Inverted bits — game keeps raw scePadRead output (pressed=bit=0)\n"
    "  • Different address — game stores pad state at a per-session address\n"
    "  • Analog-only — camera movement uses analog axis values, not digital flags\n"
    "  • Per-frame recalculation — camera mode is recomputed every frame;\n"
    "    a one-shot PNACH write is immediately overwritten (needs type-C continuous)\n"
    "  • Custom driver — game uses a proprietary pad library (e.g. licensed engines)\n"
    "  • Multi-address — camera state is spread across multiple addresses\n\n"
    "When 'estimated' is true, always verify the address in PCSX2:\n"
    "  Debug → Memory Search → search for value '0' while in normal camera,\n"
    "  then search for '1' after triggering freecam in-game."
)


def check_freecam_compatibility(game_crc: str) -> List[dict]:
    """Return input-compatibility information for all freecam entries for a game.

    Parameters
    ----------
    game_crc:   The uppercase 8-char CRC for the game (e.g. ``"E2F01792"``).

    Returns
    -------
    A list of dicts, one per freecam-related DB entry found for this CRC.
    Each dict contains:
        ``address``      — the EE memory address (uppercase, 8 chars)
        ``description``  — human-readable feature name
        ``value_type``   — ``"bool"`` / ``"float"`` / ``"button_combo"`` / …
        ``input_compat`` — one of the ``INPUT_COMPAT_LABELS`` keys
        ``compat_label`` — human-readable label from ``INPUT_COMPAT_LABELS``
        ``estimated``    — whether the address is research-derived (not verified)
        ``notes``        — full notes string from the DB entry

    Examples
    --------
    >>> results = check_freecam_compatibility("E2F01792")
    >>> [r["input_compat"] for r in results]
    ['not_applicable', 'not_applicable', 'standard_sce_pad']
    """
    crc = game_crc.upper()
    out: List[dict] = []
    for key, entry in _DB.items():
        if entry.get("game_crc", "").upper() != crc:
            continue
        desc = entry.get("description", "").lower()
        if "freecam" not in desc:
            continue
        compat = entry.get("input_compat", "unknown")
        # Extract address from key  e.g. "E2F01792:EE:00B80090"
        parts = key.split(":")
        address = parts[2] if len(parts) >= 3 else ""
        out.append({
            "address":      address,
            "description":  entry.get("description", ""),
            "value_type":   entry.get("value_type", ""),
            "input_compat": compat,
            "compat_label": INPUT_COMPAT_LABELS.get(compat, compat),
            "estimated":    entry.get("estimated", True),
            "notes":        entry.get("notes", ""),
        })
    return out


# ---------------------------------------------------------------------------
# Custom value conversion
# ---------------------------------------------------------------------------

def value_to_pnach_hex(text: str, value_type: str) -> tuple[str | None, str | None]:
    """Convert a user-supplied string to an 8-char uppercase PNACH hex value.

    Parameters
    ----------
    text:       The user's input, e.g. ``"1000"``, ``"1,000"``, ``"2.5"``.
                For ``"button_combo"`` this is the raw 8-char hex bitmask
                (e.g. ``"00000006"`` for L3+R3).
    value_type: One of:
                ``"int"``          — whole-number values (money, HP, counts)
                ``"float"``        — IEEE-754 single-precision (speed, gravity, FOV)
                ``"bool"``         — treated as int (0 or 1)
                ``"button_combo"`` — PS2 bitmask for simultaneous button combo;
                                     text must already be a valid 8-char hex string.

    Returns
    -------
    A ``(hex_str, error_msg)`` pair.  On success ``hex_str`` is an 8-char
    uppercase hex string and ``error_msg`` is ``None``.  On failure
    ``hex_str`` is ``None`` and ``error_msg`` is a user-friendly message.

    Examples
    --------
    >>> value_to_pnach_hex("1000", "int")
    ('000003E8', None)
    >>> value_to_pnach_hex("1,000,000", "int")
    ('000F4240', None)
    >>> value_to_pnach_hex("2.5", "float")
    ('40200000', None)
    >>> value_to_pnach_hex("90", "float")   # 90° FOV
    ('42B40000', None)
    >>> value_to_pnach_hex("abc", "int")
    (None, "Enter a whole number (e.g. 1000 or 1,000,000)")
    >>> value_to_pnach_hex("00000006", "button_combo")
    ('00000006', None)
    """
    clean = text.strip().replace(",", "").replace("_", "")
    if not clean:
        return None, "Value is empty"

    if value_type == "int":
        try:
            val = int(clean)
        except ValueError:
            return None, "Enter a whole number (e.g. 1000 or 1,000,000)"
        if val < 0:
            # Represent as two's-complement signed 32-bit
            val = val & 0xFFFFFFFF
        val = min(val, 0xFFFFFFFF)
        return f"{val:08X}", None

    if value_type == "float":
        try:
            fval = float(clean)
        except ValueError:
            return None, "Enter a decimal number (e.g. 2.5 or 90.0)"
        try:
            packed = struct.pack(">f", fval)
        except struct.error:
            return None, "Value out of range for a 32-bit float"
        return packed.hex().upper(), None

    if value_type == "bool":
        # Bool is stored as an int 0/1
        try:
            val = int(clean)
        except ValueError:
            return None, "Enter 0 (off) or 1 (on)"
        return f"{(1 if val else 0):08X}", None

    if value_type == "button_combo":
        # The text is already the 8-char hex bitmask chosen from the combo dropdown.
        # Accept raw hex strings up to 8 chars.
        try:
            bitmask = int(clean, 16)
        except ValueError:
            return None, "Button combo value must be a hex bitmask (e.g. 00000006)"
        if not (0 <= bitmask <= 0xFFFF):
            return None, "Button bitmask out of range (must be 0x0000–0xFFFF)"
        return f"{bitmask:08X}", None

    return None, f"Unknown value_type: {value_type!r}"
