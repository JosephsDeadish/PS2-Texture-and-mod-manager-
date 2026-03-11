"""Archive extraction utilities for PS2 Mod Manager.

Supports:
  - .zip  (Python stdlib zipfile — always available)
  - .7z   (py7zr — optional, graceful fallback if not installed)
  - Multi-part archives (common for large PS2 texture packs):
      * Named zip parts:   Pack_Part1.zip, Pack_Part2.zip, …  (extract each)
      * 7-zip volumes:     Pack.7z.001, Pack.7z.002, …        (py7zr handles)
      * Zip split volumes: Pack.z01, Pack.z02, …Pack.zip       (concatenation)

Usage:
    from src.core.archive import extract_archive, is_archive
    if is_archive(path):
        extract_archive(path, dest_dir)

    # Multi-part helpers:
    from src.core.archive import is_multipart_archive, find_multipart_parts, check_multipart_completeness
    if is_multipart_archive(path):
        ok, parts, missing = check_multipart_completeness(path)
"""

import re as _re
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple


class ArchiveError(Exception):
    pass


# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

# Extensions recognised as archives
_ZIP_EXTS = {".zip"}
_7Z_EXTS = {".7z"}
_ARCHIVE_EXTS = _ZIP_EXTS | _7Z_EXTS | {".rar"}

# ---------------------------------------------------------------------------
# Multi-part archive pattern detection
# ---------------------------------------------------------------------------

# Named zip/7z parts: Pack_Part1.zip · Pack Part 2.7z · Pack-pt3.zip
_NAMED_PART_RE = _re.compile(
    r"^(?P<base>.+?)[\s_\-]+[Pp](?:ar)?t[\s_\-]*(?P<num>\d+)\.(?P<ext>zip|7z)$"
)

# 7-zip multi-volume: Pack.7z.001, Pack.7z.002 …
_7Z_MULTI_RE = _re.compile(r"^(?P<base>.+\.7z)\.(?P<num>\d{3,})$", _re.IGNORECASE)

# Zip split volumes: Pack.z01, Pack.z02 …  (final piece is Pack.zip)
_ZIP_SPLIT_RE = _re.compile(r"^(?P<base>.+)\.z(?P<num>\d{2,})$", _re.IGNORECASE)


def is_multipart_archive(path: str) -> bool:
    """Return True if *path* matches a recognised multi-part archive naming convention.

    Recognised patterns
    -------------------
    * ``Pack_Part1.zip`` / ``Pack_Part2.7z`` — named parts (extract each independently)
    * ``Pack.7z.001`` / ``Pack.7z.002``      — 7-zip multi-volume (extract first part)
    * ``Pack.z01`` / ``Pack.z02``             — zip split volumes
    """
    name = Path(path).name
    return bool(
        _NAMED_PART_RE.match(name)
        or _7Z_MULTI_RE.match(name)
        or _ZIP_SPLIT_RE.match(name)
    )


def _parse_multipart(path: str) -> Optional[Tuple]:
    """Return ``(parent, base, part_num, kind)`` or ``None`` if not multi-part.

    *kind* is one of ``'named_zip'``, ``'named_7z'``, ``'7z_multi'``, ``'zip_split'``.
    """
    p = Path(path)
    name = p.name
    parent = p.parent

    m = _NAMED_PART_RE.match(name)
    if m:
        kind = "named_7z" if m.group("ext").lower() == "7z" else "named_zip"
        return parent, m.group("base"), int(m.group("num")), kind

    m = _7Z_MULTI_RE.match(name)
    if m:
        return parent, m.group("base"), int(m.group("num")), "7z_multi"

    m = _ZIP_SPLIT_RE.match(name)
    if m:
        return parent, m.group("base"), int(m.group("num")), "zip_split"

    return None


def find_multipart_parts(path: str) -> List[str]:
    """Return a sorted list of all sibling part-files for *path*'s archive set.

    Given e.g. ``/mods/Pack_Part1.zip`` this scans the same directory for
    ``Pack_Part2.zip``, ``Pack_Part3.zip`` etc. and returns them all sorted
    by part number.  Returns ``[]`` if *path* is not a multi-part archive.
    """
    parsed = _parse_multipart(path)
    if parsed is None:
        return []
    parent, base, _num, kind = parsed

    found: List[Tuple[int, str]] = []
    try:
        for f in parent.iterdir():
            fp = _parse_multipart(str(f))
            if fp is None:
                continue
            f_parent, f_base, f_num, f_kind = fp
            # Must be same kind and same base name (case-insensitive)
            if f_kind == kind and f_base.lower() == base.lower():
                found.append((f_num, str(f)))
        # For zip-split, the last piece is Pack.zip — add it if present
        if kind == "zip_split":
            final = parent / (base + ".zip")
            if final.exists():
                # Use a high number so it sorts last
                found.append((9999, str(final)))
    except PermissionError:
        pass

    found.sort(key=lambda x: x[0])
    return [p for _, p in found]


def check_multipart_completeness(path: str) -> Tuple[bool, List[str], int]:
    """Check whether all consecutive parts of a multi-part archive are present.

    Returns ``(is_complete, found_parts, missing_count)`` where:

    * ``is_complete``  – True when found parts form a gapless sequence starting at 1.
    * ``found_parts``  – sorted list of found part file paths (including *path* itself).
    * ``missing_count`` – estimated number of missing parts (0 when complete).
    """
    parts = find_multipart_parts(path)
    if not parts:
        # Not a multi-part — treat as complete single file
        return True, [path], 0

    nums: List[int] = []
    for p in parts:
        parsed = _parse_multipart(p)
        if parsed and parsed[3] != "zip_split":  # zip_split uses synthetic 9999
            nums.append(parsed[2])

    if not nums:
        return True, parts, 0

    nums.sort()
    expected = list(range(min(nums), max(nums) + 1))
    missing = len(expected) - len(nums)
    return missing == 0, parts, missing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_archive(path: str) -> bool:
    """Return True if *path* has a recognised archive extension (including multi-part)."""
    p = Path(path)
    if p.suffix.lower() in _ARCHIVE_EXTS:
        return True
    return is_multipart_archive(path)


def extract_archive(source_path: str, dest_dir: str) -> List[str]:
    """Extract *source_path* into *dest_dir*.

    Handles multi-part archives automatically:

    * **Named zip parts** (``Pack_Part1.zip``, ``Pack_Part2.zip`` …): every sibling
      part in the same folder is extracted in order into *dest_dir*.
    * **7-zip multi-volume** (``Pack.7z.001``): ``py7zr`` resolves sibling volumes
      automatically — only the first part needs to be passed.
    * **Zip split volumes** (``Pack.z01`` …): not natively supported; a helpful
      ``ArchiveError`` is raised explaining how to manually reassemble.

    Returns a combined list of relative paths of all extracted files.
    Raises :class:`ArchiveError` on failure.

    Notes
    -----
    - ZIP files are extracted using the Python stdlib ``zipfile`` module.
    - 7z files are extracted using ``py7zr`` if installed.
    - RAR files are not supported natively.
    - Archive members with absolute or path-traversal names are rejected.
    """
    src = Path(source_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # ── Multi-part archives ──────────────────────────────────────────────────
    if is_multipart_archive(source_path):
        parsed = _parse_multipart(source_path)
        kind = parsed[3] if parsed else ""

        if kind == "zip_split":
            raise ArchiveError(
                "Split ZIP volumes (.z01 / .z02 / …) are not natively supported.\n"
                "Please combine all parts manually:\n"
                "  • On Windows: open the .z01 file with 7-Zip and extract.\n"
                "  • On Linux/macOS: run  cat *.z0* *.zip | bsdtar -xf -\n"
                "Then import the resulting folder using ➕ Import."
            )

        if kind == "7z_multi":
            # py7zr finds sibling volumes automatically from the first-part path
            return _extract_7z(src, dest)

        if kind in ("named_zip", "named_7z"):
            parts = find_multipart_parts(source_path)
            if not parts:
                parts = [source_path]
            all_extracted: List[str] = []
            for part in parts:
                part_path = Path(part)
                if not part_path.exists():
                    raise ArchiveError(
                        f"Multi-part archive piece not found: {part_path.name}\n"
                        "Ensure all parts are in the same folder before importing."
                    )
                if part_path.suffix.lower() == ".zip":
                    all_extracted.extend(_extract_zip(part_path, dest))
                elif part_path.suffix.lower() == ".7z":
                    all_extracted.extend(_extract_7z(part_path, dest))
            return all_extracted

    # ── Standard single-file archives ───────────────────────────────────────
    ext = src.suffix.lower()

    if ext == ".zip":
        return _extract_zip(src, dest)
    elif ext == ".7z":
        return _extract_7z(src, dest)
    elif ext == ".rar":
        raise ArchiveError(
            "RAR extraction is not supported.\n"
            "Please extract the RAR file manually and import the resulting folder."
        )
    else:
        raise ArchiveError(f"Unsupported archive format: {ext!r}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_name(member_path: str) -> bool:
    """Return True if *member_path* is safe to extract (no absolute paths or
    path traversal sequences).
    """
    p = Path(member_path)
    if p.is_absolute():
        return False
    for part in p.parts:
        if part in ("..", "."):
            # single dot is harmless but we normalise it out; double-dot is dangerous
            if part == "..":
                return False
    return True


def _extract_zip(src: Path, dest: Path) -> List[str]:
    """Extract a ZIP archive, rejecting unsafe member paths."""
    if not zipfile.is_zipfile(str(src)):
        raise ArchiveError(f"File does not appear to be a valid ZIP: {src.name}")

    extracted: List[str] = []
    try:
        with zipfile.ZipFile(str(src), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                if not _safe_name(member.filename):
                    raise ArchiveError(
                        f"Archive contains unsafe path: {member.filename!r}"
                    )
                zf.extract(member, dest)
                extracted.append(member.filename)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Corrupt ZIP file: {exc}") from exc
    except OSError as exc:
        raise ArchiveError(f"Extraction failed: {exc}") from exc

    return extracted


def _extract_7z(src: Path, dest: Path) -> List[str]:
    """Extract a 7z archive (or first part of a 7z volume) using py7zr."""
    try:
        import py7zr  # type: ignore[import]
    except ImportError:
        raise ArchiveError(
            "py7zr is required for .7z extraction.\n"
            "Install it with:  pip install py7zr"
        )

    extracted: List[str] = []
    try:
        with py7zr.SevenZipFile(str(src), mode="r") as archive:
            names = archive.getnames()
            for name in names:
                if not _safe_name(name):
                    raise ArchiveError(
                        f"Archive contains unsafe path: {name!r}"
                    )
            archive.extractall(path=str(dest))
            extracted = [n for n in names if not n.endswith("/")]
    except Exception as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError(f"7z extraction failed: {exc}") from exc

    return extracted
