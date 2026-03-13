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


# DB and the two look-up indexes (built at load time and on reload).
_DB: Dict[str, dict] = {}
# CRC (upper) → list of DB keys for that game.
_IDX_CRC: Dict[str, List[str]] = {}
# Serial (upper) → list of DB keys for that serial.
_IDX_SERIAL: Dict[str, List[str]] = {}

# Regex used to extract a PS2 serial from an embedded "Game Title (SLUS-NNNNN)" string.
_SERIAL_RE = re.compile(
    r'\(([A-Z]{4}-\d{5})\)',
    re.IGNORECASE,
)


def _build_indexes(db: Dict[str, dict]) -> None:
    """Build the CRC and serial look-up indexes from *db* in O(n)."""
    global _IDX_CRC, _IDX_SERIAL
    idx_crc: Dict[str, List[str]] = {}
    idx_serial: Dict[str, List[str]] = {}
    for key, entry in db.items():
        crc = entry.get("game_crc", "").upper()
        if crc:
            idx_crc.setdefault(crc, []).append(key)
        serial = entry.get("game_serial", "").upper()
        if serial:
            idx_serial.setdefault(serial, []).append(key)
        elif (m := _SERIAL_RE.search(entry.get("game", ""))):
            idx_serial.setdefault(m.group(1).upper(), []).append(key)
    _IDX_CRC = idx_crc
    _IDX_SERIAL = idx_serial


def _init_db() -> None:
    global _DB
    _DB = _load_db()
    _build_indexes(_DB)


_init_db()


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

    Backed by a pre-built index so the look-up is O(1) regardless of DB size.
    """
    serial_upper = serial.strip().upper()
    results: List[dict] = []
    for key in _IDX_SERIAL.get(serial_upper, []):
        entry = _DB.get(key)
        if entry is not None:
            results.append({"key": key, **entry})
    return results


def entries_for_crc(game_crc: str) -> List[dict]:
    """Return all DB entries for a game identified by its CRC.

    Each returned dict includes the raw DB ``key`` plus all stored fields.

    Backed by a pre-built index so the look-up is O(1) regardless of DB size.
    """
    crc_upper = game_crc.strip().upper()
    results: List[dict] = []
    for key in _IDX_CRC.get(crc_upper, []):
        entry = _DB.get(key)
        if entry is not None:
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
      * ``size``       — optional size keyword.  If absent, falls back to the
                         ``patch_type`` field from the DB entry if present,
                         otherwise defaults to ``"word"``.
      * ``code_method``— optional code method (from DB).  Entries with
                         ``code_method="continuous_write"`` emit an extra
                         comment warning that the patch must be re-applied
                         each frame (use extended/type-C cheats if needed).
      * ``verification_status`` — optional; emitted as a comment tag.

    The returned string is ready to be written to ``<CRC>.pnach``.
    """
    lines = [
        f"gametitle={game_title}",
        f"comment={comment}",
        "",
    ]
    for p in patches:
        desc = (p.get("description") or "").strip()
        vs   = p.get("verification_status", "")
        cm   = p.get("code_method", "")

        # Build the comment line with optional verification / method tags
        comment_parts = []
        if desc:
            comment_parts.append(desc)
        if vs in ("estimated",):
            comment_parts.append("[estimated — verify address before use]")
        if vs in ("community_verified", "verified"):
            comment_parts.append("[verified]")
        if cm == "continuous_write":
            comment_parts.append("[continuous — game resets each frame]")

        if comment_parts:
            lines.append(f"// {' | '.join(comment_parts)}")

        proc  = p.get("processor", "EE").upper()
        addr  = p.get("address", "00000000").upper().zfill(8)
        # Prefer explicit "size", then "patch_type" from DB, then "word"
        size  = p.get("size") or p.get("patch_type") or "word"
        value = p.get("value", "00000000").upper().zfill(8)
        lines.append(f"patch=1,{proc},{addr},{size},{value}")
    return "\n".join(lines) + "\n"


def list_all_serials_in_db() -> List[Tuple[str, str]]:
    """Return a sorted list of ``(serial, game_title)`` pairs found in the DB.

    Used by the Code Builder game picker to populate its dropdown.

    Backed by the pre-built serial index so this is O(unique-serials) instead
    of O(all-entries).
    """
    seen: Dict[str, str] = {}
    for serial_upper, keys in _IDX_SERIAL.items():
        if not keys:
            continue
        entry = _DB.get(keys[0], {})
        game = entry.get("game", "")
        title = game.split(" (")[0] if " (" in game else game
        seen[serial_upper] = title
    return sorted(seen.items(), key=lambda x: x[1])


# ---------------------------------------------------------------------------
# DB refresh (used by tests / tooling)
# ---------------------------------------------------------------------------

def reload_db() -> int:
    """Reload the address database from disk and rebuild look-up indexes.

    Returns entry count.
    """
    global _DB
    _DB = _load_db()
    _build_indexes(_DB)
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
    for key in _IDX_CRC.get(crc, []):
        entry = _DB.get(key)
        if entry is None:
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
# Per-game verification summary
# ---------------------------------------------------------------------------

#: Human-readable labels for each verification_status value.
VERIFICATION_STATUS_LABELS: Dict[str, str] = {
    "verified":              "✅ Verified — confirmed by hands-on PCSX2 testing",
    "community_verified":    "👥 Community verified — confirmed by community reports",
    "estimated":             "🔬 Estimated — research-derived address, not yet confirmed",
    "reported_not_working":  "❌ Not working — known to fail in at least one version",
}

#: Human-readable labels for each code_method value.
CODE_METHOD_LABELS: Dict[str, str] = {
    "static_write":    "Static write — patch is written once and persists",
    "continuous_write":"Continuous write — patch must be re-applied every frame",
    "conditional":     "Conditional — patch only applies when a condition is met",
    "multi_address":   "Multi-address — effect requires patching several locations",
}

#: Human-readable labels for each patch_type (PCSX2 size keyword).
PATCH_TYPE_LABELS: Dict[str, str] = {
    "word":     "word (32-bit) — most cheats and floats",
    "short":    "short (16-bit) — 16-bit counters",
    "byte":     "byte (8-bit) — single-byte flags",
    "extended": "extended — conditional/multi-line pnach cheat",
}


def get_game_verification_summary(game_crc: str) -> dict:
    """Return a per-game summary of verification status and code methods.

    Parameters
    ----------
    game_crc:
        Uppercase 8-char CRC for the game (e.g. ``"2EB5B9A9"``).

    Returns
    -------
    A dict with the following keys:

    ``game_title``           — display title from first matching DB entry
    ``game_serial``          — serial from first matching entry
    ``total_entries``        — total DB entries for this game
    ``verification_counts``  — dict mapping status → count
    ``code_method_counts``   — dict mapping method → count
    ``patch_type_counts``    — dict mapping patch_type → count
    ``community_verified``   — list of (description, code_method) for verified entries
    ``estimated``            — list of (description, code_method) for estimated entries
    ``not_working``          — list of (description, reason) for known-broken entries
    ``methods_used``         — sorted list of unique code_method values present
    ``has_continuous_writes``— bool, True if any entry requires continuous writes
    ``has_multi_address``    — bool, True if any entry spans multiple addresses
    ``notes``                — human-readable summary string
    """
    crc = game_crc.strip().upper()
    keys = _IDX_CRC.get(crc, [])
    matching = [(key, _DB[key]) for key in keys if key in _DB]

    if not matching:
        return {
            "game_title": "",
            "game_serial": "",
            "total_entries": 0,
            "verification_counts": {},
            "code_method_counts": {},
            "patch_type_counts": {},
            "community_verified": [],
            "estimated": [],
            "not_working": [],
            "methods_used": [],
            "has_continuous_writes": False,
            "has_multi_address": False,
            "notes": f"No DB entries found for CRC {crc}.",
        }

    first_entry = matching[0][1]
    game_title = first_entry.get("game", "")
    game_serial = first_entry.get("game_serial", "")

    v_counts: Dict[str, int] = {}
    cm_counts: Dict[str, int] = {}
    pt_counts: Dict[str, int] = {}
    verified_list: List[dict] = []
    estimated_list: List[dict] = []
    not_working_list: List[dict] = []

    for _key, entry in matching:
        vs = entry.get("verification_status", "estimated")
        cm = entry.get("code_method", "static_write")
        pt = entry.get("patch_type", "word")
        desc = entry.get("description", "")
        cat  = entry.get("category", "")

        v_counts[vs] = v_counts.get(vs, 0) + 1
        cm_counts[cm] = cm_counts.get(cm, 0) + 1
        pt_counts[pt] = pt_counts.get(pt, 0) + 1

        if vs in ("verified", "community_verified"):
            verified_list.append({
                "description": desc,
                "category":    cat,
                "code_method": cm,
                "patch_type":  pt,
                "value_type":  entry.get("value_type", ""),
            })
        elif vs == "reported_not_working":
            not_working_list.append({
                "description": desc,
                "notes":       entry.get("notes", ""),
            })
        else:
            estimated_list.append({
                "description": desc,
                "category":    cat,
                "code_method": cm,
                "patch_type":  pt,
            })

    methods_used = sorted(set(cm_counts.keys()))
    has_cw = "continuous_write" in cm_counts
    has_ma = "multi_address" in cm_counts

    # Build a plain-English notes paragraph
    total = len(matching)
    cv_count = v_counts.get("community_verified", 0) + v_counts.get("verified", 0)
    est_count = v_counts.get("estimated", 0)
    nw_count  = v_counts.get("reported_not_working", 0)

    notes_parts = [
        f"{game_title}: {total} DB entries.",
        f"  {cv_count} community/verified, {est_count} estimated, {nw_count} known-broken.",
    ]
    if has_cw:
        notes_parts.append(
            f"  ⚠ {cm_counts['continuous_write']} entries require continuous writes "
            "(game resets the value each frame — use type-C/extended pnach if available)."
        )
    if has_ma:
        notes_parts.append(
            f"  ℹ {cm_counts['multi_address']} entries span multiple addresses for one effect."
        )
    if est_count > 0:
        notes_parts.append(
            f"  🔬 {est_count} addresses are research-derived and unverified; "
            "confirm in PCSX2 Debug → Memory Search before use."
        )

    return {
        "game_title":           game_title,
        "game_serial":          game_serial,
        "total_entries":        total,
        "verification_counts":  v_counts,
        "code_method_counts":   cm_counts,
        "patch_type_counts":    pt_counts,
        "community_verified":   verified_list,
        "estimated":            estimated_list,
        "not_working":          not_working_list,
        "methods_used":         methods_used,
        "has_continuous_writes":has_cw,
        "has_multi_address":    has_ma,
        "notes":                "\n".join(notes_parts),
    }


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
