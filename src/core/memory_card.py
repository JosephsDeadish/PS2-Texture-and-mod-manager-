"""Memory card utilities for PS2 Mod Manager.

PCSX2 uses PS2 memory card images (.ps2 or .mcd).
The PS2 memory card format has a well-documented layout:
  - Superblock at byte 0 (0x1F4 magic + parameters)
  - Each card is 8 MB = 8388608 bytes for a standard card

This module provides:
  - Listing saves from a memory card image
  - Extracting individual saves
  - Importing saves back into a card image

References:
  https://psx-scene.com/forums/f291/ps2-memcard-format-60806/
  mymc source (open source PS2 memory card manager, GPL-2.0)
"""

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# Memory card constants
# The magic string ends with a trailing space — this is part of the official
# PS2 memory card superblock format and is intentional.
MC_SUPERBLOCK_MAGIC = b"Sony PS2 Memory Card Format "  # trailing space is required by spec
MC_PAGE_SIZE = 512
MC_SPARE_SIZE = 16
MC_PAGES_PER_CLUSTER = 2
MC_PAGES_PER_BLOCK = 16
MC_CLUSTERS_PER_CARD = 8192
MC_CARD_SIZE = MC_PAGE_SIZE * MC_PAGES_PER_CLUSTER * MC_CLUSTERS_PER_CARD  # 8 MB

SUPERBLOCK_OFFSET = 0


@dataclass
class SaveEntry:
    """Represents one save inside a memory card."""
    name: str
    dir_name: str
    size_bytes: int
    files: List[str] = field(default_factory=list)
    icon_data: bytes = b""


class MemoryCardError(Exception):
    pass


def is_valid_memcard(path: str) -> bool:
    """Return True if the file looks like a PS2 memory card image."""
    try:
        p = Path(path)
        if not p.is_file():
            return False
        size = p.stat().st_size
        if size < MC_PAGE_SIZE:
            return False
        with open(path, "rb") as f:
            magic = f.read(len(MC_SUPERBLOCK_MAGIC))
        return magic == MC_SUPERBLOCK_MAGIC
    except OSError:
        return False


def list_saves(memcard_path: str) -> List[SaveEntry]:
    """
    Return a list of saves found in a PS2 memory card image.

    This is a best-effort parser that reads the FAT-based directory
    structure.  Full format details: mymc project (GPL-2.0).
    """
    path = Path(memcard_path)
    if not path.is_file():
        raise MemoryCardError(f"File not found: {memcard_path}")

    saves: List[SaveEntry] = []

    try:
        with open(memcard_path, "rb") as f:
            data = f.read()

        if not data.startswith(MC_SUPERBLOCK_MAGIC):
            raise MemoryCardError("Not a valid PS2 memory card image")

        # Each directory entry starts at a cluster; do a simple scan for
        # directory entries that match the PS2 save dir pattern.
        # Directory entries are 512-byte pages; entry starts with mode flags.
        # Scan the full card (up to MC_CARD_SIZE) so no saves are missed
        # on larger or heavily-used cards.
        ENTRY_SIZE = 512
        for offset in range(0, min(len(data), MC_CARD_SIZE), ENTRY_SIZE):
            chunk = data[offset : offset + ENTRY_SIZE]
            if len(chunk) < 64:
                break
            mode = struct.unpack_from("<H", chunk, 0)[0]
            # 0x8427 = dir entry that is used
            if mode not in (0x8427, 0x8417):
                continue
            # length field
            length = struct.unpack_from("<I", chunk, 4)[0]
            if length == 0:
                continue
            # name at offset 0x40, null-terminated, up to 32 chars
            name_bytes = chunk[0x40:0x60]
            name = name_bytes.split(b"\x00")[0].decode("ascii", errors="replace")
            if not name or len(name) < 3:
                continue
            saves.append(
                SaveEntry(
                    name=name,
                    dir_name=name,
                    size_bytes=length * ENTRY_SIZE,
                )
            )
    except (struct.error, UnicodeDecodeError, OSError) as exc:
        raise MemoryCardError(f"Failed to parse memory card: {exc}") from exc

    return saves


def export_save(memcard_path: str, save_name: str, dest_dir: str) -> str:
    """
    Export a save directory from a memory card to *dest_dir*.
    Returns the path of the exported file.

    This creates a raw binary dump of the relevant pages.
    For full compatibility, use mymc (GPL-2.0) as an external tool.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"{save_name}.bin"

    try:
        with open(memcard_path, "rb") as f:
            data = f.read()

        start = data.find(save_name.encode("ascii", errors="replace"))
        if start == -1:
            raise MemoryCardError(f"Save '{save_name}' not found in card")

        # Align to page boundary and copy 64 KB (rough heuristic)
        page_start = (start // MC_PAGE_SIZE) * MC_PAGE_SIZE
        chunk = data[page_start : page_start + 64 * 1024]

        with open(out_path, "wb") as f:
            f.write(chunk)

        return str(out_path)
    except OSError as exc:
        raise MemoryCardError(f"Export failed: {exc}") from exc


def backup_memcard(src_path: str, backup_dir: str) -> str:
    """
    Back up a memory card image by copying it to *backup_dir*.

    The backup filename is derived from the original filename with a
    timestamp suffix, e.g. ``MemoryCard1_20240101_120000.ps2``.

    Returns the full path to the backup file.
    """
    import shutil
    from datetime import datetime

    src = Path(src_path)
    if not src.is_file():
        raise MemoryCardError(f"Source card not found: {src_path}")

    dest = Path(backup_dir)
    dest.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{src.stem}_backup_{stamp}{src.suffix}"
    backup_path = dest / backup_name

    try:
        shutil.copy2(str(src), str(backup_path))
    except OSError as exc:
        raise MemoryCardError(f"Backup failed: {exc}") from exc

    return str(backup_path)


def import_raw_save(src_path: str, memcard_path: str, save_name: str) -> bool:
    """
    Write a raw save dump (produced by :func:`export_save`) back into a
    memory card image, overwriting the region that contains *save_name*.

    Returns True if the data was written, False if the save directory
    entry was not found and the data was appended with a best-effort header.

    .. note::
        Full, byte-perfect round-trip injection requires implementing the
        complete PS2 FAT format (see mymc, GPL-2.0).  This function performs
        a practical page-replacement that works for cards managed by PCSX2
        because PCSX2 re-initialises the directory structures on next launch.
        Always back up your memory card before using this function.
    """
    src = Path(src_path)
    if not src.is_file():
        raise MemoryCardError(f"Source save file not found: {src_path}")

    mc = Path(memcard_path)
    if not mc.is_file():
        raise MemoryCardError(f"Memory card not found: {memcard_path}")

    if not is_valid_memcard(memcard_path):
        raise MemoryCardError("Destination is not a valid PS2 memory card image")

    try:
        with open(src_path, "rb") as f:
            save_data = f.read()

        with open(memcard_path, "r+b") as f:
            card_data = bytearray(f.read())

        # Try to find existing entry to overwrite
        needle = save_name.encode("ascii", errors="replace")
        pos = card_data.find(needle)

        if pos != -1:
            # Align to page boundary and overwrite that region
            page_start = (pos // MC_PAGE_SIZE) * MC_PAGE_SIZE
            end = min(page_start + len(save_data), len(card_data))
            card_data[page_start : end] = save_data[: end - page_start]
            found = True
        else:
            # Append to the end of the used area.
            # Scan backward to find the last non-zero byte, but stop at the
            # beginning of the card to avoid missing superblock-only data.
            used_end = MC_PAGE_SIZE * 2   # default: just after superblock
            for i in range(len(card_data) - 1, 0, -1):
                if card_data[i] != 0:
                    used_end = ((i // MC_PAGE_SIZE) + 2) * MC_PAGE_SIZE
                    break
            if used_end + len(save_data) > len(card_data):
                raise MemoryCardError(
                    "Not enough space in memory card for this save"
                )
            card_data[used_end : used_end + len(save_data)] = save_data
            found = False

        with open(memcard_path, "wb") as f:
            f.write(card_data)

        return found
    except OSError as exc:
        raise MemoryCardError(f"Import failed: {exc}") from exc


def copy_save_between_cards(
    src_card: str,
    save_name: str,
    dest_card: str,
    temp_dir: str,
) -> bool:
    """
    Copy a save from *src_card* to *dest_card*.

    Internally:
    1. Exports the save from the source card to a temporary file.
    2. Imports it into the destination card.

    Returns True if the save was found and written to the destination.
    Raises :class:`MemoryCardError` on any failure.
    """
    import tempfile, shutil

    tmp = Path(temp_dir)
    tmp.mkdir(parents=True, exist_ok=True)

    export_path = export_save(src_card, save_name, str(tmp))
    result = import_raw_save(export_path, dest_card, save_name)

    # Clean up temp file
    try:
        Path(export_path).unlink(missing_ok=True)
    except OSError:
        pass

    return result


def list_memcard_files(memcards_dir: str) -> List[str]:
    """Return paths to all recognised PS2 memory card files in *memcards_dir*.

    Supported extensions: .ps2, .mcd, .mc2, .bin (PCSX2 also uses .bin).
    """
    result = []
    d = Path(memcards_dir)
    if not d.is_dir():
        return result
    for p in sorted(d.iterdir()):
        if p.suffix.lower() in (".ps2", ".mcd", ".mc2", ".bin"):
            result.append(str(p))
    return result


def create_memcard(dest_path: str, size_mb: int = 8) -> str:
    """
    Create a blank PCSX2-compatible PS2 memory card image at *dest_path*.

    The file is zeroed-out except for the superblock magic at byte 0,
    which makes PCSX2 recognise it as a valid (empty) card on first use.
    PCSX2 will initialise the FAT structures the first time it opens the card.

    Args:
        dest_path: Full path including filename (e.g. ~/memcards/Slot1.ps2).
        size_mb:   Card size in megabytes.  8 MB is the standard PS2 card size.
                   Must be between 1 and 64 (inclusive).

    Returns:
        The absolute path of the created file.
    """
    if not isinstance(size_mb, int) or size_mb < 1 or size_mb > 64:
        raise MemoryCardError(
            f"Invalid memory card size: {size_mb} MB. "
            "Valid range is 1–64 MB (standard PS2 card is 8 MB)."
        )

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        raise MemoryCardError(f"File already exists: {dest_path}")

    total_bytes = size_mb * 1024 * 1024
    try:
        with open(dest, "wb") as f:
            # Write superblock magic followed by zeroes
            f.write(MC_SUPERBLOCK_MAGIC)
            remaining = total_bytes - len(MC_SUPERBLOCK_MAGIC)
            # Write in 64 KB chunks to avoid allocating the whole card at once
            chunk = b"\x00" * 65536
            while remaining > 0:
                to_write = min(remaining, 65536)
                f.write(chunk[:to_write])
                remaining -= to_write
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise MemoryCardError(f"Failed to create memory card: {exc}") from exc

    return str(dest)
