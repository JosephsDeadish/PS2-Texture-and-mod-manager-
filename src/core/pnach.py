"""PNACH file parser, validator and merger for PS2 Mod Manager.

PNACH (PS2 cheat/patch) file format::

    // Optional comment lines (start with //)
    gametitle=Game Title
    comment=Some description

    patch=ENABLED,EE,ADDRESS,SIZE,VALUE
    patch=ENABLED,IOP,ADDRESS,SIZE,VALUE

Where:
    ENABLED : 1 = enabled, 0 = disabled
    EE / IOP: processor
    ADDRESS : 8-hex-digit memory address
    SIZE    : word | short | byte | extended | double
    VALUE   : hex value

The PNACH filename is the game CRC (8 hex digits) followed by ``.pnach``,
e.g.  ``F0A235B4.pnach``.

This module provides:
- :func:`parse_pnach` — read a PNACH file into structured data
- :func:`write_pnach` — write structured data back to a file
- :func:`merge_pnach_files` — combine patch lines from multiple files for the
  same game, deduplicating and preserving enabled/disabled state
- :func:`extract_game_crc` — derive the game CRC from a PNACH filename
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PatchLine:
    """One ``patch=...`` line from a PNACH file."""
    enabled: int        # 0 or 1
    processor: str      # "EE" or "IOP"
    address: str        # 8-char hex address string (upper-cased)
    size: str           # word | short | byte | extended | double
    value: str          # hex value string (upper-cased)
    comment: str = ""   # inline comment after the line (rarely used)

    # Canonical key used for deduplication: same address+processor == same patch
    @property
    def dedup_key(self) -> Tuple[str, str]:
        return (self.processor.upper(), self.address.upper())

    def to_line(self) -> str:
        base = f"patch={self.enabled},{self.processor},{self.address},{self.size},{self.value}"
        if self.comment:
            base += f"  //{self.comment}"
        return base


@dataclass
class PnachFile:
    """Parsed representation of a PNACH file."""
    game_crc: str                  # 8-char hex, upper-case
    game_title: str = ""
    comment: str = ""
    header_comments: List[str] = field(default_factory=list)  # // lines before patches
    patches: List[PatchLine] = field(default_factory=list)

    def to_text(self) -> str:
        lines: List[str] = []
        for c in self.header_comments:
            lines.append(c)
        if self.game_title:
            lines.append(f"gametitle={self.game_title}")
        if self.comment:
            lines.append(f"comment={self.comment}")
        if lines:
            lines.append("")
        for p in self.patches:
            lines.append(p.to_line())
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_RE = re.compile(
    r"^\s*patch\s*=\s*"
    r"(\d+)\s*,\s*"              # enabled
    r"(\w+)\s*,\s*"              # processor
    r"([0-9A-Fa-f]{1,8})\s*,\s*" # address
    r"(\w+)\s*,\s*"              # size
    r"([0-9A-Fa-f]+)"            # value
    r"(?:\s*//\s*(.*))?$",       # optional inline comment
    re.IGNORECASE,
)


def extract_game_crc(pnach_path: str) -> str:
    """
    Derive the game CRC from a PNACH filename.
    Returns the 8-character CRC in upper-case, or empty string if the
    filename does not match the expected pattern.
    """
    name = Path(pnach_path).stem
    if re.fullmatch(r"[0-9A-Fa-f]{8}", name):
        return name.upper()
    return ""


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_pnach(path: str) -> PnachFile:
    """
    Parse a PNACH file.  Returns a :class:`PnachFile`.
    Raises :class:`ValueError` if the file cannot be read.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"PNACH file not found: {path}")

    game_crc = extract_game_crc(str(p))
    result = PnachFile(game_crc=game_crc)

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"Cannot read PNACH file: {exc}") from exc

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//"):
            result.header_comments.append(line)
            continue
        low = line.lower()
        if low.startswith("gametitle="):
            result.game_title = line.split("=", 1)[1].strip()
            continue
        if low.startswith("comment="):
            result.comment = line.split("=", 1)[1].strip()
            continue
        m = _PATCH_RE.match(line)
        if m:
            result.patches.append(PatchLine(
                enabled=int(m.group(1)),
                processor=m.group(2).upper(),
                address=m.group(3).upper().zfill(8),
                size=m.group(4).lower(),
                value=m.group(5).upper(),
                comment=m.group(6) or "",
            ))

    return result


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_pnach(pnach: PnachFile, dest_path: str) -> str:
    """
    Write a :class:`PnachFile` to *dest_path*.
    Returns the absolute path of the written file.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(pnach.to_text(), encoding="utf-8")
    return str(dest)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_pnach_files(
    pnach_paths: List[str],
    dest_dir: str,
    game_crc: str = "",
    game_title: str = "",
) -> str:
    """
    Combine patch lines from multiple PNACH files into a single output file.

    Rules:
    - All enabled ``patch=`` lines are collected from every input file.
    - Duplicate entries (same processor + address) are deduplicated: the first
      occurrence (in the order the files are given) wins.
    - Disabled ``patch=0,...`` lines are included only if the address is not
      already covered by an enabled entry.
    - A header comment block records the sources that were merged.

    Returns the path of the written merged PNACH file.
    Raises :class:`ValueError` if the input list is empty.
    """
    if not pnach_paths:
        raise ValueError("No PNACH files to merge")

    parsed: List[PnachFile] = []
    for path in pnach_paths:
        try:
            parsed.append(parse_pnach(path))
        except ValueError:
            pass  # Skip unreadable files

    if not parsed:
        raise ValueError("No valid PNACH files could be parsed")

    # Determine output CRC
    crc = game_crc or parsed[0].game_crc
    title = game_title or next((p.game_title for p in parsed if p.game_title), "")

    # Collect patches — enabled ones first, then disabled
    seen_keys: Dict[Tuple[str, str], PatchLine] = {}  # dedup_key → PatchLine
    disabled_patches: List[PatchLine] = []

    for pf in parsed:
        for patch in pf.patches:
            key = patch.dedup_key
            if patch.enabled:
                if key not in seen_keys:
                    seen_keys[key] = patch
            else:
                disabled_patches.append(patch)

    # Stable sort by address
    merged_patches = list(seen_keys.values())
    merged_patches.sort(key=lambda p: p.address)

    # Include disabled patches that don't clash with enabled ones
    for dp in disabled_patches:
        if dp.dedup_key not in seen_keys:
            merged_patches.append(dp)
            seen_keys[dp.dedup_key] = dp

    header_comments = [
        "// Merged by PS2 Mod Manager",
        "// Sources:",
    ]
    for i, path in enumerate(pnach_paths):
        header_comments.append(f"//   {i+1}. {Path(path).name}")

    merged = PnachFile(
        game_crc=crc,
        game_title=title,
        header_comments=header_comments,
        patches=merged_patches,
    )

    filename = f"{crc}.pnach" if crc else "merged.pnach"
    dest_path = str(Path(dest_dir) / filename)
    return write_pnach(merged, dest_path)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

@dataclass
class PnachConflict:
    """Two PNACH files that both write to the same address."""
    address: str
    processor: str
    file_a: str          # path to first PNACH
    value_a: str
    file_b: str          # path to second PNACH
    value_b: str


def find_pnach_conflicts(pnach_paths: List[str]) -> List[PnachConflict]:
    """
    Find address-level conflicts between PNACH files.

    Returns a list of :class:`PnachConflict` for every (address, processor)
    pair that is written by more than one file with *different* values.
    """
    # Maps dedup_key → (file_path, value, size)
    seen: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    conflicts: List[PnachConflict] = []

    for path in pnach_paths:
        try:
            pf = parse_pnach(path)
        except ValueError:
            continue
        for patch in pf.patches:
            if not patch.enabled:
                continue
            key = patch.dedup_key
            if key in seen:
                prev_path, prev_val, _ = seen[key]
                if prev_val.upper() != patch.value.upper():
                    conflicts.append(PnachConflict(
                        address=patch.address,
                        processor=patch.processor,
                        file_a=prev_path,
                        value_a=prev_val,
                        file_b=path,
                        value_b=patch.value,
                    ))
            else:
                seen[key] = (path, patch.value, patch.size)

    return conflicts


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Valid size identifiers accepted by PCSX2
_VALID_SIZES = {"byte", "short", "word", "double", "extended"}

# Maximum value widths (in hex nibbles) per size type
_SIZE_MAX_NIBBLES = {
    "byte":     2,   # 1 byte  = 0xFF
    "short":    4,   # 2 bytes = 0xFFFF
    "word":     8,   # 4 bytes = 0xFFFFFFFF
    "double":   16,  # 8 bytes
    "extended": 16,  # extended is used for multi-line / special codes
}

# PCSX2 EE RAM is 32 MB: 0x00000000–0x01FFFFFF (mirrored at 0x20000000)
# IOP RAM is 2 MB: 0x00000000–0x001FFFFF
_EE_MAX_ADDR  = 0x1FFFFFFF
_IOP_MAX_ADDR = 0x001FFFFF

_VALID_PROCESSORS = {"EE", "IOP"}


@dataclass
class ValidationIssue:
    """A single problem found in a PNACH file."""
    line_number: int        # 1-based, 0 if not applicable
    severity: str           # "error" | "warning"
    code: str               # short machine-readable code, e.g. "invalid_size"
    message: str            # human-readable description
    patch: Optional["PatchLine"] = None


def validate_pnach_file(path: str) -> List[ValidationIssue]:
    """
    Validate a PNACH file and return a list of :class:`ValidationIssue`.

    Checks performed:
    - File must have a valid 8-hex-digit CRC as its name (error).
    - ``gametitle`` should be non-empty (warning).
    - Each ``patch=`` line is checked for:
        * Unknown processor (error)
        * Invalid size keyword (error)
        * Value too wide for the declared size (error)
        * EE address out of expected RAM range (warning)
        * IOP address out of expected RAM range (warning)
    - Duplicate address entries (same processor+address) with different values are
      flagged as conflicts (warning) — same as ``find_pnach_conflicts`` but inline.
    - Duplicate address entries with identical values are flagged as redundant (warning).

    Returns an empty list if the file is clean.
    Raises :class:`ValueError` if the file cannot be read.
    """
    p = Path(path)
    issues: List[ValidationIssue] = []

    # --- CRC in filename ---
    crc = extract_game_crc(str(p))
    if not crc:
        issues.append(ValidationIssue(
            line_number=0,
            severity="error",
            code="invalid_filename",
            message=(
                f"Filename '{p.name}' is not a valid PNACH filename. "
                "PCSX2 requires the filename to be exactly the 8-digit game CRC, "
                f"e.g. 'ABCD1234.pnach'."
            ),
        ))

    pf = parse_pnach(path)  # raises ValueError if unreadable

    if not pf.game_title:
        issues.append(ValidationIssue(
            line_number=0,
            severity="warning",
            code="missing_gametitle",
            message="No 'gametitle=' line found. Adding one helps identify the file.",
        ))

    # Track addresses for duplicate detection
    seen_addr: Dict[Tuple[str, str], Tuple[str, int]] = {}  # key → (value, line_num)
    line_num = 0

    for patch in pf.patches:
        line_num += 1
        proc = patch.processor.upper()
        size = patch.size.lower()

        if proc not in _VALID_PROCESSORS:
            issues.append(ValidationIssue(
                line_number=line_num,
                severity="error",
                code="invalid_processor",
                message=(
                    f"Unknown processor '{patch.processor}' at address {patch.address}. "
                    f"Valid values are: {', '.join(sorted(_VALID_PROCESSORS))}."
                ),
                patch=patch,
            ))

        if size not in _VALID_SIZES:
            issues.append(ValidationIssue(
                line_number=line_num,
                severity="error",
                code="invalid_size",
                message=(
                    f"Unknown size '{patch.size}' at address {patch.address}. "
                    f"Valid values are: {', '.join(sorted(_VALID_SIZES))}."
                ),
                patch=patch,
            ))
        else:
            max_nibbles = _SIZE_MAX_NIBBLES[size]
            val_stripped = patch.value.lstrip("0") or "0"
            if len(val_stripped) > max_nibbles:
                issues.append(ValidationIssue(
                    line_number=line_num,
                    severity="error",
                    code="value_overflow",
                    message=(
                        f"Value '{patch.value}' is too large for size '{size}' "
                        f"(max {max_nibbles} hex digits) at address {patch.address}."
                    ),
                    patch=patch,
                ))

        # Address range check
        try:
            addr_int = int(patch.address, 16)
            if proc == "EE" and addr_int > _EE_MAX_ADDR:
                issues.append(ValidationIssue(
                    line_number=line_num,
                    severity="warning",
                    code="address_out_of_range",
                    message=(
                        f"EE address {patch.address} exceeds expected PS2 RAM range "
                        f"(max 0x{_EE_MAX_ADDR:08X}). Check the code is correct."
                    ),
                    patch=patch,
                ))
            elif proc == "IOP" and addr_int > _IOP_MAX_ADDR:
                issues.append(ValidationIssue(
                    line_number=line_num,
                    severity="warning",
                    code="address_out_of_range",
                    message=(
                        f"IOP address {patch.address} exceeds expected IOP RAM range "
                        f"(max 0x{_IOP_MAX_ADDR:08X}). Check the code is correct."
                    ),
                    patch=patch,
                ))
        except ValueError:
            pass  # already caught by regex in parse_pnach

        # Duplicate detection
        key = patch.dedup_key
        if key in seen_addr:
            prev_val, prev_line = seen_addr[key]
            if prev_val.upper() == patch.value.upper():
                issues.append(ValidationIssue(
                    line_number=line_num,
                    severity="warning",
                    code="redundant_duplicate",
                    message=(
                        f"Address {patch.address} ({proc}) appears more than once "
                        f"with the same value '{patch.value}' (first at line {prev_line}). "
                        "The duplicate entry is redundant and can be removed."
                    ),
                    patch=patch,
                ))
            else:
                issues.append(ValidationIssue(
                    line_number=line_num,
                    severity="warning",
                    code="address_conflict",
                    message=(
                        f"Address {patch.address} ({proc}) is set to '{patch.value}' here "
                        f"but was already set to '{prev_val}' at line {prev_line}. "
                        "Only the last value will take effect."
                    ),
                    patch=patch,
                ))
        else:
            seen_addr[key] = (patch.value, line_num)

    return issues
