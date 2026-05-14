"""Conflict detection and resolution for PS2 Mod Manager.

This module scans installed PCSX2 content for conflicts — situations where
two or more items would interfere with each other at runtime.  Examples
include:

* The same CRC ``.pnach`` file existing in *both* ``cheats/`` and
  ``cheats_ws/`` (PCSX2 may apply both, causing unexpected behaviour).
* Two ``.pnach`` files that write to the **same memory address** for the same
  game CRC (one patch will silently overwrite the other).
* Two cover-art images for the same serial with different extensions (PCSX2
  picks one arbitrarily).
* Duplicate texture files with identical content inside a serial's
  ``replacements/`` folder (often caused by merged or repeated pack installs).

Public API::

    from src.core.conflict_resolver import (
        Conflict,
        ConflictSeverity,
        resolve_pnach_conflicts,
        resolve_cover_art_conflicts,
        resolve_all_conflicts,
        auto_fix_conflict,
    )

    conflicts = resolve_all_conflicts(config)
    for c in conflicts:
        print(c.severity, c.title)
        if c.can_auto_fix:
            auto_fix_conflict(c)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# (processor, address, size, value) for a single enabled PNACH patch line
PatchSignature = Tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------

class ConflictResolution(str, Enum):
    """User's resolution choice for a :class:`TextureOverwriteConflict`.

    Attributes
    ----------
    PENDING:
        No decision has been made yet (default).
    PACK_A:
        Use the texture provided by Pack A; Pack B's version is ignored.
    PACK_B:
        Use the texture provided by Pack B; Pack A's version is ignored.
    SKIP:
        Leave the conflict without applying any resolution.
    """

    PENDING = "pending"
    PACK_A  = "pack_a"
    PACK_B  = "pack_b"
    SKIP    = "skip"

    def __str__(self) -> str:  # noqa: D105
        return self.value


class ConflictSeverity(str, Enum):
    """Severity level for a detected conflict."""
    ERROR   = "error"    # will definitely cause problems at runtime
    WARNING = "warning"  # may cause unexpected behaviour
    INFO    = "info"     # cosmetic / harmless duplicates


# ---------------------------------------------------------------------------
# Human-readable labels
# ---------------------------------------------------------------------------

SEVERITY_LABEL: Dict[str, str] = {
    ConflictSeverity.ERROR:   "❌ Error",
    ConflictSeverity.WARNING: "⚠️  Warning",
    ConflictSeverity.INFO:    "ℹ️  Info",
}

SEVERITY_COLOR: Dict[str, str] = {
    ConflictSeverity.ERROR:   "#c0392b",
    ConflictSeverity.WARNING: "#e67e22",
    ConflictSeverity.INFO:    "#2980b9",
}


# ---------------------------------------------------------------------------
# Conflict dataclass
# ---------------------------------------------------------------------------

@dataclass
class Conflict:
    """A detected conflict between two or more installed items.

    Attributes
    ----------
    conflict_type:
        Short identifier for the conflict category, e.g.
        ``"pnach_duplicate_crc"``, ``"pnach_address_clash"``,
        ``"cover_art_duplicate"``.
    severity:
        How serious the conflict is (:class:`ConflictSeverity`).
    title:
        Short human-readable title shown in the conflict list.
    description:
        Full explanation of what the conflict is and why it matters.
    items:
        The file paths (as :class:`~pathlib.Path`) involved in the conflict.
    resolution:
        Recommended action the user should take.
    can_auto_fix:
        ``True`` when :func:`auto_fix_conflict` can resolve this conflict
        automatically (e.g. by deleting a redundant file).
    """

    conflict_type: str
    severity: ConflictSeverity
    title: str
    description: str
    items: List[Path] = field(default_factory=list)
    resolution: str = ""
    can_auto_fix: bool = False

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABEL.get(self.severity, str(self.severity))

    @property
    def severity_color(self) -> str:
        return SEVERITY_COLOR.get(self.severity, "#888888")

    @property
    def item_names(self) -> List[str]:
        return [p.name for p in self.items]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CRC_RE   = re.compile(r'^[0-9A-Fa-f]{8}$')
_PS2_SERIAL_RE = re.compile(r'^[A-Z]{2,4}-\d{3,5}$', re.IGNORECASE)

_PNACH_PATCH_LINE_RE = re.compile(
    r'^\s*patch\s*=\s*\d+\s*,\s*EE\s*,\s*([0-9A-Fa-f]{8})',
    re.IGNORECASE,
)


def _crc_from_pnach_name(path: Path) -> Optional[str]:
    """Return the 8-char upper-case CRC from a ``.pnach`` filename, or None."""
    if path.suffix.lower() != ".pnach":
        return None
    stem = path.stem.upper()
    if _CRC_RE.match(stem):
        return stem
    return None


def _read_pnach_addresses(path: Path) -> Set[str]:
    """Return the set of EE memory addresses patched in *path*.

    Each ``patch=N,EE,XXXXXXXX,…`` line contributes its 8-hex-digit address.
    Unreadable files return an empty set.
    """
    addresses: Set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _PNACH_PATCH_LINE_RE.match(line)
            if m:
                addresses.add(m.group(1).upper())
    except OSError:
        pass
    return addresses


def _read_pnach_patch_set(path: Path) -> Set[PatchSignature]:
    """Return a set of enabled patch signatures from *path*.

    Each entry is ``(processor, address, size, value)``. Unreadable files
    return an empty set.
    """
    try:
        from src.core.pnach import parse_pnach
    except Exception:
        return set()
    try:
        parsed = parse_pnach(str(path))
    except ValueError as exc:
        logger.warning("Failed to parse PNACH file %s: %s", path, exc)
        return set()
    patches: Set[PatchSignature] = set()
    for patch in parsed.patches:
        if not patch.enabled:
            continue
        patches.add((
            patch.processor.upper(),
            patch.address.upper(),
            patch.size.lower(),
            patch.value.upper(),
        ))
    return patches


def _select_pnach_delete_path(
    p_file: Path,
    c_file: Path,
    p_set: Set[PatchSignature],
    c_set: Set[PatchSignature],
) -> Path:
    """Choose which PNACH file should be deleted when auto-fixing duplicates."""
    if p_set and c_set:
        if p_set < c_set:
            return p_file
        if c_set < p_set:
            return c_file
    # Identical or unknown — prefer deleting the cheats_ws file if possible
    for candidate in (p_file, c_file):
        if any(part.lower() == "cheats_ws" for part in candidate.parts):
            return candidate
    return c_file


def _pnach_can_auto_fix(
    p_set: Set[PatchSignature],
    c_set: Set[PatchSignature],
    p_file: Optional[Path] = None,
    c_file: Optional[Path] = None,
) -> bool:
    """Return True when one PNACH's enabled patches are contained in the other."""
    if p_set and c_set:
        return p_set <= c_set or c_set <= p_set
    if p_file and c_file:
        p_hash = _hash_file(p_file)
        c_hash = _hash_file(c_file)
        return bool(p_hash) and p_hash == c_hash
    return False


def _is_ps2_serial(name: str) -> bool:
    return bool(_PS2_SERIAL_RE.match(name))


# ---------------------------------------------------------------------------
# Per-type conflict scanners
# ---------------------------------------------------------------------------

def resolve_pnach_conflicts(
    pnach_path: str,
    cheats_path: str,
) -> List[Conflict]:
    """Detect conflicts involving ``.pnach`` files.

    Checks performed:

    1. **Duplicate CRC across folders** – the same CRC ``.pnach`` exists in
       *both* ``cheats/`` (regular patches) and ``cheats_ws/`` (widescreen /
       cheat patches).  PCSX2 will apply both, which can cause glitches.
    2. **Address clash within the same CRC** – two ``.pnach`` files with
       the same CRC (in different folders) that patch the **same** EE
       memory address.  The second write silently overwrites the first.

    Parameters
    ----------
    pnach_path:
        Path to PCSX2's ``cheats/`` directory.
    cheats_path:
        Path to PCSX2's ``cheats_ws/`` directory.

    Returns
    -------
    list[Conflict]
        All detected ``.pnach``-related conflicts.
    """
    conflicts: List[Conflict] = []

    pnach_dir  = Path(pnach_path)  if pnach_path  else None
    cheats_dir = Path(cheats_path) if cheats_path else None

    # Build CRC → file map for each directory
    def _crc_map(directory: Optional[Path]) -> Dict[str, Path]:
        if not directory or not directory.is_dir():
            return {}
        result: Dict[str, Path] = {}
        try:
            for f in sorted(directory.iterdir()):
                crc = _crc_from_pnach_name(f)
                if crc:
                    result[crc] = f
        except PermissionError:
            pass
        return result

    pnach_files  = _crc_map(pnach_dir)
    cheats_files = _crc_map(cheats_dir)

    # 1. Duplicate CRC across cheats/ and cheats_ws/
    shared_crcs = set(pnach_files) & set(cheats_files)
    for crc in sorted(shared_crcs):
        p_file = pnach_files[crc]
        c_file = cheats_files[crc]

        # Check for address clashes
        p_addrs = _read_pnach_addresses(p_file)
        c_addrs = _read_pnach_addresses(c_file)
        clashing = p_addrs & c_addrs
        p_set = _read_pnach_patch_set(p_file)
        c_set = _read_pnach_patch_set(c_file)
        auto_fixable = _pnach_can_auto_fix(p_set, c_set, p_file, c_file)
        delete_target = _select_pnach_delete_path(p_file, c_file, p_set, c_set) if auto_fixable else None

        if clashing:
            auto_note = ""
            if auto_fixable and delete_target is not None:
                auto_note = (
                    "\n\nAuto-fix is available because one file's enabled patches are "
                    f"fully contained in the other file's patches. Auto-fix will delete: {delete_target.name}"
                )
            conflicts.append(Conflict(
                conflict_type="pnach_address_clash",
                severity=ConflictSeverity.ERROR,
                title=f"Address clash: {crc}.pnach ({len(clashing)} address(es))",
                description=(
                    f"Two PNACH files for CRC {crc} patch the same EE memory "
                    f"address(es): {', '.join(sorted(clashing)[:5])}{'…' if len(clashing) > 5 else ''}.\n"
                    f"The file in cheats_ws/ will overwrite patches applied by "
                    f"the file in cheats/, causing one set of codes to have no effect."
                    f"{auto_note}"
                ),
                items=[p_file, c_file],
                resolution=(
                    "Remove the duplicate patch lines from one of the files, "
                    "or delete the file whose patches are superseded."
                ),
                can_auto_fix=auto_fixable,
            ))
        else:
            conflicts.append(Conflict(
                conflict_type="pnach_duplicate_crc",
                severity=ConflictSeverity.WARNING,
                title=f"Duplicate CRC: {crc}.pnach in cheats/ and cheats_ws/",
                description=(
                    f"The file {crc}.pnach exists in both your cheats/ and "
                    f"cheats_ws/ directories.  PCSX2 will apply both files.  "
                    f"This is usually harmless if the patches are different, "
                    f"but may indicate accidental duplication."
                ),
                items=[p_file, c_file],
                resolution=(
                    "If the two files contain the same patches, delete one. "
                    "If they are intentionally different, no action is needed."
                ),
                can_auto_fix=auto_fixable,
            ))

    return conflicts


def resolve_cover_art_conflicts(cover_art_path: str) -> List[Conflict]:
    """Detect duplicate cover-art images for the same PS2 serial.

    PCSX2 loads cover art as ``<SERIAL>.png``; if both ``SLUS-20062.png``
    and ``SLUS-20062.jpg`` exist PCSX2 may load only one, making the other
    redundant.

    Parameters
    ----------
    cover_art_path:
        Path to PCSX2's ``covers/`` directory.

    Returns
    -------
    list[Conflict]
        One :class:`Conflict` per serial that has more than one image file.
    """
    conflicts: List[Conflict] = []
    covers_dir = Path(cover_art_path) if cover_art_path else None
    if not covers_dir or not covers_dir.is_dir():
        return conflicts

    serial_to_files: Dict[str, List[Path]] = {}
    try:
        files = sorted(covers_dir.iterdir())
    except PermissionError:
        return conflicts

    for f in files:
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        serial = f.stem.upper()
        if not _is_ps2_serial(serial):
            continue
        serial_to_files.setdefault(serial, []).append(f)

    for serial, file_list in sorted(serial_to_files.items()):
        if len(file_list) > 1:
            conflicts.append(Conflict(
                conflict_type="cover_art_duplicate",
                severity=ConflictSeverity.INFO,
                title=f"Duplicate cover art: {serial} ({len(file_list)} files)",
                description=(
                    f"Multiple cover-art images exist for serial {serial}: "
                    f"{', '.join(f.name for f in file_list)}.  "
                    f"PCSX2 prefers .png files; the others are redundant."
                ),
                items=file_list,
                resolution=(
                    "Keep only the .png version and delete the others.  "
                    "Auto-fix will remove all non-.png duplicates."
                ),
                can_auto_fix=True,
            ))

    return conflicts


def resolve_texture_conflicts(textures_path: str) -> List[Conflict]:
    """Detect duplicate texture data inside ``replacements/`` folders.

    Looks for multiple texture files in the same serial's replacements tree
    that share identical content (matching file hashes). This avoids flagging
    organized sub-directories that do not actually duplicate data.

    Parameters
    ----------
    textures_path:
        Path to PCSX2's ``textures/`` directory.

    Returns
    -------
    list[Conflict]
        Detected texture-related conflicts.
    """
    conflicts: List[Conflict] = []
    tex_dir = Path(textures_path) if textures_path else None
    if not tex_dir or not tex_dir.is_dir():
        return conflicts

    try:
        serial_dirs = [d for d in sorted(tex_dir.iterdir()) if d.is_dir()]
    except PermissionError:
        return conflicts

    for serial_dir in serial_dirs:
        serial = serial_dir.name.upper()
        if not _is_ps2_serial(serial):
            continue

        replacements = serial_dir / "replacements"
        if not replacements.is_dir():
            continue

        hash_map: Dict[str, List[Path]] = {}
        try:
            for dirpath, _dirs, files in os.walk(replacements):
                for fname in files:
                    if Path(fname).suffix.lower() not in _TEXTURE_EXTS:
                        continue
                    path = Path(dirpath) / fname
                    digest = _hash_file(path)
                    if digest:
                        hash_map.setdefault(digest, []).append(path)
        except PermissionError:
            continue

        for digest, files in sorted(hash_map.items()):
            if len(files) < 2:
                continue
            sample_names = ", ".join(p.name for p in files[:4])
            conflicts.append(Conflict(
                conflict_type="texture_duplicate_hash",
                severity=ConflictSeverity.INFO,
                title=f"Duplicate texture data: {serial} ({len(files)} copies)",
                description=(
                    f"Multiple texture files inside {serial}/replacements share the same "
                    f"content hash. This often happens when packs are merged or copied "
                    f"into organized sub-folders. Example files: {sample_names}"
                    f"{'…' if len(files) > 4 else ''}."
                ),
                items=files[:8],
                resolution=(
                    "If these are redundant copies, keep a single version and remove "
                    "the duplicates. Otherwise no action is required."
                ),
                can_auto_fix=False,
            ))

    return conflicts


# ---------------------------------------------------------------------------
# Texture overwrite conflict detection (cross-pack filename clash)
# ---------------------------------------------------------------------------

@dataclass
class TextureOverwriteConflict:
    """Detailed information about two packs providing the same texture file.

    This captures everything needed for the Texture Pack Conflict Visualiser:

    * The PCSX2 texture filename (``texture_id``) both packs compete for.
    * Which packs are involved and the path to each pack's copy.
    * The game serial this conflict belongs to.
    * Alpha-channel type and file-size metadata for both versions.
    * The user's resolution choice (default :attr:`ConflictResolution.PENDING`).

    Attributes
    ----------
    texture_id:
        The PCSX2 replacement filename both packs provide
        (e.g. ``abc12345-3b0f5ac99a2574db-00006653.png``).
    serial:
        PS2 disc serial (e.g. ``SLUS-20062``).
    pack_a_id:
        Identifier / folder name of the first pack.
    pack_a_path:
        Path to the texture file inside pack A's replacements folder.
    pack_b_id:
        Identifier / folder name of the second pack.
    pack_b_path:
        Path to the texture file inside pack B's replacements folder.
    same_content:
        ``True`` when both files have identical content (detected via
        byte-for-byte comparison of the first 8 KiB).
    alpha_type_a:
        Alpha-channel descriptor for pack A's texture:
        ``"has_alpha"``, ``"opaque"``, or ``"unknown"``.
    alpha_type_b:
        Alpha-channel descriptor for pack B's texture.
    pack_a_size_bytes:
        File size of pack A's texture in bytes (0 when unreadable).
    pack_b_size_bytes:
        File size of pack B's texture in bytes (0 when unreadable).
    resolution:
        The user's choice for resolving this conflict
        (:class:`ConflictResolution`).  Defaults to
        :attr:`ConflictResolution.PENDING`.
    """

    texture_id: str
    serial: str
    pack_a_id: str
    pack_a_path: Path
    pack_b_id: str
    pack_b_path: Path
    same_content: bool = False
    alpha_type_a: str = "unknown"
    alpha_type_b: str = "unknown"
    pack_a_size_bytes: int = 0
    pack_b_size_bytes: int = 0
    resolution: str = ConflictResolution.PENDING

    @property
    def winner_id(self) -> Optional[str]:
        """Return the winning pack ID, or ``None`` when unresolved.

        Returns pack A's ID when :attr:`resolution` is
        :attr:`ConflictResolution.PACK_A`, pack B's ID when it is
        :attr:`ConflictResolution.PACK_B`, and ``None`` otherwise.
        """
        if self.resolution == ConflictResolution.PACK_A:
            return self.pack_a_id
        if self.resolution == ConflictResolution.PACK_B:
            return self.pack_b_id
        return None

    @property
    def conflict_summary(self) -> str:
        """One-line human-readable summary."""
        kind = "identical content" if self.same_content else "different content"
        return (
            f"{self.serial}: texture '{self.texture_id}' claimed by "
            f"'{self.pack_a_id}' and '{self.pack_b_id}' ({kind})"
        )

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "texture_id": self.texture_id,
            "serial": self.serial,
            "pack_a_id": self.pack_a_id,
            "pack_a_path": str(self.pack_a_path),
            "pack_b_id": self.pack_b_id,
            "pack_b_path": str(self.pack_b_path),
            "same_content": self.same_content,
            "alpha_type_a": self.alpha_type_a,
            "alpha_type_b": self.alpha_type_b,
            "pack_a_size_bytes": self.pack_a_size_bytes,
            "pack_b_size_bytes": self.pack_b_size_bytes,
            "resolution": str(self.resolution),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextureOverwriteConflict":
        """Deserialise from a dictionary produced by :meth:`to_dict`."""
        return cls(
            texture_id=data["texture_id"],
            serial=data["serial"],
            pack_a_id=data["pack_a_id"],
            pack_a_path=Path(data["pack_a_path"]),
            pack_b_id=data["pack_b_id"],
            pack_b_path=Path(data["pack_b_path"]),
            same_content=bool(data.get("same_content", False)),
            alpha_type_a=data.get("alpha_type_a", "unknown"),
            alpha_type_b=data.get("alpha_type_b", "unknown"),
            pack_a_size_bytes=int(data.get("pack_a_size_bytes", 0)),
            pack_b_size_bytes=int(data.get("pack_b_size_bytes", 0)),
            resolution=data.get("resolution", ConflictResolution.PENDING),
        )


def _files_have_same_content(path_a: Path, path_b: Path, check_bytes: int = 8192) -> bool:
    """Return True if the first *check_bytes* of both files are identical."""
    try:
        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            return fa.read(check_bytes) == fb.read(check_bytes)
    except OSError:
        return False


#: PNG file signature (first 8 bytes).
_PNG_MAGIC: bytes = b"\x89PNG\r\n\x1a\n"

#: PNG color-type byte values that include an alpha channel.
_PNG_ALPHA_COLOR_TYPES: frozenset[int] = frozenset({4, 6})

#: PNG color-type byte values that are fully opaque.
_PNG_OPAQUE_COLOR_TYPES: frozenset[int] = frozenset({0, 2, 3})


def _detect_alpha_type(path: Path) -> str:
    """Return the alpha-channel type string for a texture file.

    Supports PNG (IHDR color-type inspection).  All other formats return
    ``"unknown"``.

    Returns
    -------
    str
        One of ``"has_alpha"``, ``"opaque"``, or ``"unknown"``.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "unknown"

    if path.suffix.lower() == ".png":
        # PNG layout: 8-byte magic, then IHDR chunk:
        #   4 bytes length, 4 bytes "IHDR", 4 bytes width, 4 bytes height,
        #   1 byte bit-depth, 1 byte color-type  → offset 25
        if len(data) < 26 or data[:8] != _PNG_MAGIC:
            return "unknown"
        color_type = data[25]
        if color_type in _PNG_ALPHA_COLOR_TYPES:
            return "has_alpha"
        if color_type in _PNG_OPAQUE_COLOR_TYPES:
            return "opaque"
        return "unknown"

    # DDS, TGA, BMP, etc. — alpha detection would require format-specific
    # parsing; return unknown to keep things simple.
    return "unknown"


def _file_size_bytes(path: Path) -> int:
    """Return the size of *path* in bytes, or 0 on error."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a hex hash for *path*, or empty string on error."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                hasher.update(chunk)
    except OSError:
        return ""
    return hasher.hexdigest()


#: Image extensions scanned for overwrite conflict detection.
_TEXTURE_EXTS: frozenset[str] = frozenset({
    ".png", ".dds", ".bmp", ".tga", ".jpg", ".jpeg",
})


def _scan_replacements_dir(
    replacements: Path,
) -> Dict[str, Path]:
    """Return a dict of {filename → Path} for all texture files under *replacements*."""
    result: Dict[str, Path] = {}
    try:
        for dirpath, _dirs, files in os.walk(replacements):
            for fname in files:
                if Path(fname).suffix.lower() in _TEXTURE_EXTS:
                    # Key on the basename — this is what PCSX2 matches against.
                    result.setdefault(fname, Path(dirpath) / fname)
    except PermissionError:
        pass
    return result


def resolve_texture_overwrite_conflicts(
    textures_path: str,
) -> List[TextureOverwriteConflict]:
    """Detect texture filename conflicts between packs installed for the same serial.

    For each game serial that has **multiple** sub-directories inside its
    ``replacements/`` folder (each sub-directory treated as a separate
    pack), this function finds texture files whose basename appears in
    more than one pack.

    Because PCSX2 matches replacement textures by filename, two packs
    providing a file with the same name will conflict — only one can be
    active.

    Parameters
    ----------
    textures_path:
        Path to PCSX2's ``textures/`` directory.

    Returns
    -------
    list[TextureOverwriteConflict]
        One entry per (serial, texture_id, pack_A, pack_B) combination
        that conflicts.  Sorted by serial then texture_id.
    """
    conflicts: List[TextureOverwriteConflict] = []
    tex_dir = Path(textures_path) if textures_path else None
    if not tex_dir or not tex_dir.is_dir():
        return conflicts

    try:
        serial_dirs = sorted(
            d for d in tex_dir.iterdir()
            if d.is_dir() and _is_ps2_serial(d.name)
        )
    except PermissionError:
        return conflicts

    for serial_dir in serial_dirs:
        serial = serial_dir.name.upper()
        replacements = serial_dir / "replacements"
        if not replacements.is_dir():
            continue

        # Each sub-directory is treated as a separate pack.
        try:
            pack_dirs = sorted(
                d for d in replacements.iterdir() if d.is_dir()
            )
        except PermissionError:
            continue

        if len(pack_dirs) < 2:
            continue

        # Build {filename → Path} map per pack
        pack_maps: List[Tuple[str, Dict[str, Path]]] = []
        for pack_dir in pack_dirs:
            fmap = _scan_replacements_dir(pack_dir)
            if fmap:
                pack_maps.append((pack_dir.name, fmap))

        if len(pack_maps) < 2:
            continue

        # Find filenames present in more than one pack
        # Only compare pairs to produce individual conflict records
        for i in range(len(pack_maps)):
            pack_a_id, map_a = pack_maps[i]
            for j in range(i + 1, len(pack_maps)):
                pack_b_id, map_b = pack_maps[j]
                shared = set(map_a) & set(map_b)
                for tid in sorted(shared):
                    path_a = map_a[tid]
                    path_b = map_b[tid]
                    same = _files_have_same_content(path_a, path_b)
                    conflicts.append(TextureOverwriteConflict(
                        texture_id=tid,
                        serial=serial,
                        pack_a_id=pack_a_id,
                        pack_a_path=path_a,
                        pack_b_id=pack_b_id,
                        pack_b_path=path_b,
                        same_content=same,
                        alpha_type_a=_detect_alpha_type(path_a),
                        alpha_type_b=_detect_alpha_type(path_b),
                        pack_a_size_bytes=_file_size_bytes(path_a),
                        pack_b_size_bytes=_file_size_bytes(path_b),
                    ))

    conflicts.sort(key=lambda c: (c.serial, c.texture_id, c.pack_a_id))
    return conflicts


# ---------------------------------------------------------------------------
# Conflict resolution session
# ---------------------------------------------------------------------------

class ConflictResolutionSession:
    """Track and apply user resolution choices for texture overwrite conflicts.

    Wraps a list of :class:`TextureOverwriteConflict` objects and allows the
    user (or an automated policy) to mark each one as resolved in favour of
    Pack A, Pack B, or skipped.

    Example::

        from src.core.conflict_resolver import (
            ConflictResolutionSession,
            ConflictResolution,
            resolve_texture_overwrite_conflicts,
        )

        raw = resolve_texture_overwrite_conflicts(textures_path)
        session = ConflictResolutionSession(raw)
        session.resolve("SLUS-20062", "abc.png", ConflictResolution.PACK_A)
        print(session.summary())
    """

    def __init__(self, conflicts: List[TextureOverwriteConflict]) -> None:
        self._conflicts: List[TextureOverwriteConflict] = list(conflicts)

    # ------------------------------------------------------------------
    # Resolving individual conflicts
    # ------------------------------------------------------------------

    def resolve(
        self,
        serial: str,
        texture_id: str,
        resolution: ConflictResolution,
    ) -> bool:
        """Set the *resolution* for every conflict matching *serial* + *texture_id*.

        Returns ``True`` if at least one conflict was found and updated.
        """
        found = False
        for c in self._conflicts:
            if c.serial == serial and c.texture_id == texture_id:
                c.resolution = resolution
                found = True
        return found

    def resolve_all(
        self,
        resolution: ConflictResolution,
        *,
        overwrite: bool = False,
    ) -> int:
        """Apply *resolution* to all unresolved (PENDING) conflicts.

        Parameters
        ----------
        resolution:
            The :class:`ConflictResolution` to set.
        overwrite:
            When ``True``, overwrite existing non-PENDING resolutions too.

        Returns
        -------
        int
            Number of conflicts updated.
        """
        count = 0
        for c in self._conflicts:
            if overwrite or c.resolution == ConflictResolution.PENDING:
                c.resolution = resolution
                count += 1
        return count

    # ------------------------------------------------------------------
    # Counts and listing
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        """Total number of conflicts in this session."""
        return len(self._conflicts)

    @property
    def resolved_count(self) -> int:
        """Number of conflicts that have a non-PENDING resolution."""
        return sum(
            1 for c in self._conflicts
            if c.resolution != ConflictResolution.PENDING
        )

    @property
    def unresolved_count(self) -> int:
        """Number of conflicts still marked PENDING."""
        return sum(
            1 for c in self._conflicts
            if c.resolution == ConflictResolution.PENDING
        )

    def conflicts_for_serial(self, serial: str) -> List[TextureOverwriteConflict]:
        """Return all conflicts for a specific game serial."""
        return [c for c in self._conflicts if c.serial == serial]

    def all_conflicts(self) -> List[TextureOverwriteConflict]:
        """Return all conflicts in this session (copy of the internal list)."""
        return list(self._conflicts)

    # ------------------------------------------------------------------
    # Structured detail for UI display
    # ------------------------------------------------------------------

    def get_conflict_detail(self, serial: str, texture_id: str) -> Optional[dict]:
        """Return a structured detail dictionary for the conflict visualiser.

        The returned dict is suitable for direct use in a UI panel:

        .. code-block:: python

            {
                "texture_id": "abc.png",
                "serial": "SLUS-20062",
                "pack_a": {
                    "id": "PackA",
                    "path": "/textures/SLUS-20062/replacements/PackA/abc.png",
                    "size_bytes": 12345,
                    "alpha_type": "has_alpha",
                },
                "pack_b": {
                    "id": "PackB",
                    "path": "/textures/SLUS-20062/replacements/PackB/abc.png",
                    "size_bytes": 11999,
                    "alpha_type": "opaque",
                },
                "same_content": False,
                "resolution": "pending",
                "winner_id": None,
            }

        Returns ``None`` if no matching conflict is found.
        """
        for c in self._conflicts:
            if c.serial == serial and c.texture_id == texture_id:
                return {
                    "texture_id": c.texture_id,
                    "serial": c.serial,
                    "pack_a": {
                        "id": c.pack_a_id,
                        "path": str(c.pack_a_path),
                        "size_bytes": c.pack_a_size_bytes,
                        "alpha_type": c.alpha_type_a,
                    },
                    "pack_b": {
                        "id": c.pack_b_id,
                        "path": str(c.pack_b_path),
                        "size_bytes": c.pack_b_size_bytes,
                        "alpha_type": c.alpha_type_b,
                    },
                    "same_content": c.same_content,
                    "resolution": str(c.resolution),
                    "winner_id": c.winner_id,
                }
        return None

    def summary(self) -> dict:
        """Return a high-level summary dictionary of the session.

        .. code-block:: python

            {
                "total": 5,
                "resolved": 3,
                "unresolved": 2,
                "serials_affected": ["SLUS-20062", "SCUS-97232"],
            }
        """
        return {
            "total": self.total,
            "resolved": self.resolved_count,
            "unresolved": self.unresolved_count,
            "serials_affected": sorted({c.serial for c in self._conflicts}),
        }


def resolve_all_conflicts(config) -> List[Conflict]:
    """Run all conflict detectors and return a combined sorted list.

    Parameters
    ----------
    config:
        An :class:`~src.models.mod.AppConfig` instance (or any object with
        ``pnach_path``, ``cheats_path``, ``cover_art_path``,
        ``textures_path`` string attributes).

    Returns
    -------
    list[Conflict]
        All detected conflicts, sorted by severity (errors first) then title.
    """
    pnach_path     = getattr(config, "pnach_path", "")     or ""
    cheats_path    = getattr(config, "cheats_path", "")    or ""
    cover_art_path = getattr(config, "cover_art_path", "") or ""
    textures_path  = getattr(config, "textures_path", "")  or ""

    all_conflicts: List[Conflict] = []
    all_conflicts.extend(resolve_pnach_conflicts(pnach_path, cheats_path))
    all_conflicts.extend(resolve_cover_art_conflicts(cover_art_path))
    all_conflicts.extend(resolve_texture_conflicts(textures_path))

    severity_order = {
        ConflictSeverity.ERROR:   0,
        ConflictSeverity.WARNING: 1,
        ConflictSeverity.INFO:    2,
    }
    all_conflicts.sort(key=lambda c: (severity_order.get(c.severity, 9), c.title))
    return all_conflicts


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------

def auto_fix_conflict(conflict: Conflict) -> Tuple[bool, str]:
    """Attempt to automatically resolve *conflict*.

    Currently supports:

    * ``cover_art_duplicate`` – deletes all non-``.png`` duplicates (keeps the
      ``.png`` file).
    * ``pnach_duplicate_crc`` – deletes the redundant file when one PNACH file
      fully contains the other.
    * ``pnach_address_clash`` – same as above when the overlapping patches are
      identical and one file is a strict subset.

    Parameters
    ----------
    conflict:
        The conflict to fix.

    Returns
    -------
    tuple[bool, str]
        ``(success, message)`` – ``True`` if the fix was applied without
        error, with a human-readable message describing what was done.
    """
    if not conflict.can_auto_fix:
        return False, "This conflict cannot be auto-fixed."

    if conflict.conflict_type in ("pnach_duplicate_crc", "pnach_address_clash"):
        if len(conflict.items) != 2:
            return False, "Auto-fix expects exactly two PNACH files."
        p_file, c_file = conflict.items
        p_set = _read_pnach_patch_set(p_file)
        c_set = _read_pnach_patch_set(c_file)
        if not _pnach_can_auto_fix(p_set, c_set, p_file, c_file):
            return False, (
                "Auto-fix is only available when one file's enabled patches "
                "are fully contained in the other."
            )
        delete_path = _select_pnach_delete_path(p_file, c_file, p_set, c_set)
        try:
            delete_path.unlink()
        except OSError as exc:
            return False, f"Could not delete {delete_path.name}: {exc}"
        return True, f"Deleted duplicate PNACH file: {delete_path.name}"

    if conflict.conflict_type == "cover_art_duplicate":
        deleted: List[str] = []
        errors:  List[str] = []
        for path in conflict.items:
            if path.suffix.lower() != ".png":
                try:
                    path.unlink()
                    deleted.append(path.name)
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
        if errors:
            return False, "Some files could not be deleted:\n" + "\n".join(errors)
        if deleted:
            return True, f"Deleted {len(deleted)} duplicate file(s): {', '.join(deleted)}"
        return True, "No non-.png files to remove."

    return False, f"Auto-fix not implemented for conflict type: {conflict.conflict_type!r}"
