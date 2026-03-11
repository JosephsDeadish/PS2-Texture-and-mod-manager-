"""Archive extraction utilities for PS2 Mod Manager.

Supports:
  - .zip  (Python stdlib zipfile — always available)
  - .7z   (py7zr — optional, graceful fallback if not installed)

Usage:
    from src.core.archive import extract_archive, is_archive
    if is_archive(path):
        extract_archive(path, dest_dir)
"""

import zipfile
from pathlib import Path
from typing import List


class ArchiveError(Exception):
    pass


# Extensions recognised as archives
_ZIP_EXTS = {".zip"}
_7Z_EXTS = {".7z"}
_ARCHIVE_EXTS = _ZIP_EXTS | _7Z_EXTS | {".rar"}


def is_archive(path: str) -> bool:
    """Return True if *path* has a recognised archive extension."""
    return Path(path).suffix.lower() in _ARCHIVE_EXTS


def extract_archive(source_path: str, dest_dir: str) -> List[str]:
    """
    Extract *source_path* into *dest_dir*.

    Returns a list of relative paths of all extracted files.
    Raises ArchiveError on failure.

    Notes:
      - ZIP files are extracted using the Python stdlib ``zipfile`` module.
      - 7z files are extracted using ``py7zr`` if installed; otherwise an
        ArchiveError is raised with installation instructions.
      - RAR files are not supported natively.  A helpful error is raised.
      - Archive members with absolute or path-traversal names are rejected to
        prevent directory traversal attacks.
    """
    src = Path(source_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

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


def _safe_name(member_path: str) -> bool:
    """
    Return True if *member_path* is safe to extract (no absolute paths or
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
    """Extract a 7z archive using py7zr."""
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
