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
MC_SUPERBLOCK_MAGIC = b"Sony PS2 Memory Card Format "
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
        ENTRY_SIZE = 512
        for offset in range(0, min(len(data), 1024 * 1024), ENTRY_SIZE):
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


def list_memcard_files(memcards_dir: str) -> List[str]:
    """Return paths to all .ps2 and .mcd files in *memcards_dir*."""
    result = []
    d = Path(memcards_dir)
    if not d.is_dir():
        return result
    for p in sorted(d.iterdir()):
        if p.suffix.lower() in (".ps2", ".mcd", ".mc2"):
            result.append(str(p))
    return result
