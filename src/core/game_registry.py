"""PS2 game serial / ID recognition utilities.

PS2 game serials follow this pattern:
    <REGION_CODE>-<5-digit number>

Region codes:
    SLUS / SCUS — North America
    SLES / SCES — Europe (and PAL regions)
    SLPS / SCPS — Japan
    SLKA / SCKA — Korea
    SLAJ / SCAJ — Asia
    SLPM / SCPM — Japan (platinum)
    SLEH / SCEH — Europe (others)
    PBPX          — Disc ID variant

Common filename patterns that embed the serial:
    SLUS_20062.pnach            PNACH (underscores instead of dash)
    SLUS-20062.png              Cover art
    SLUS20062.jpg               Fused (no separator)

PNACH filenames use the **game CRC** (8 hex digits), *not* the serial, so
we can only detect serial if the filename itself contains SLUS/SCUS/etc.

Usage::

    from src.core.game_registry import detect_game_serial, serial_to_display

    serial = detect_game_serial("SLUS-20062.pnach")   # -> "SLUS-20062"
    serial = detect_game_serial("SLUS_20062.png")     # -> "SLUS-20062"
    serial = detect_game_serial("SLUS20062_HD.zip")   # -> "SLUS-20062"
    display = serial_to_display("SLUS-20062")         # -> "SLUS-20062 (SpyroEnterDragonfly?)"
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Serial pattern
# ---------------------------------------------------------------------------

_SERIAL_PATTERN = re.compile(
    r"(?<!\w)(SL(?:US|PS|ES|KA|AJ|PM|EH)|SC(?:US|PS|ES|KA|EH|AJ)|PBPX)"
    r"[_\-]?(\d{5})(?!\d)",
    re.IGNORECASE,
)

# Known game serials -> game title (small curated set; real-world lookup uses GameTDB)
_KNOWN_SERIALS: dict[str, str] = {
    "SLUS-20062": "Spyro: Enter the Dragonfly",
    "SLUS-20439": "Spyro: A Hero's Tail",
    "SCUS-97120": "Jak and Daxter: The Precursor Legacy",
    "SCUS-97265": "Jak II",
    "SCUS-97330": "Jak 3",
    "SCUS-97131": "Ratchet & Clank",
    "SCUS-97199": "Ratchet & Clank: Going Commando",
    "SCUS-97268": "Ratchet & Clank: Up Your Arsenal",
    "SLUS-20552": "Kingdom Hearts",
    "SLUS-20145": "Kingdom Hearts",
    "SLUS-21005": "Kingdom Hearts II",
    "SLUS-20891": "God of War",
    "SLUS-21441": "God of War II",
    "SLUS-20721": "Shadow of the Colossus",
    "SCES-53005": "Shadow of the Colossus (PAL)",
    "SLUS-20678": "Ico",
    "SCES-50760": "Ico (PAL)",
    "SLUS-20486": "Gran Turismo 3: A-spec",
    "SLUS-21163": "Gran Turismo 4",
    "SLPS-25516": "Gran Turismo 4 (JP)",
    "SLUS-20444": "Grand Theft Auto: San Andreas",
    "SLUS-20688": "Grand Theft Auto: San Andreas (v2)",
    "SLUS-20140": "Grand Theft Auto: Vice City",
    "SLUS-20792": "Final Fantasy XII",
    "SLUS-21162": "Final Fantasy XII (Greatest Hits)",
    "SLPS-25520": "Final Fantasy XII (JP)",
    "SLUS-20770": "Metal Gear Solid 3: Snake Eater",
    "SLUS-20487": "Devil May Cry",
    "SLUS-20902": "Devil May Cry 3",
    "SLUS-20773": "Silent Hill 2",
    "SLUS-20507": "Silent Hill 3",
    "SLES-52232": "Silent Hill 4",
    "SLUS-21068": "Resident Evil 4",
    "SLUS-21370": "Persona 4",
    "SLUS-21270": "Persona 3 FES",
    "SLUS-20793": "Dragon Quest VIII",
    "SLUS-21277": "Okami",
    "SLUS-21426": "Guitar Hero III",
    "SLUS-21323": "Guitar Hero II",
    "SLUS-20940": "Guitar Hero",
    "SLUS-21219": "Tekken 5",
    "SLUS-20882": "Tekken 4",
    "SLUS-20162": "Tekken Tag Tournament",
    "SLUS-20574": "Soul Calibur II",
    "SLUS-20762": "Street Fighter Alpha Anthology",
    "SLES-53662": "Baldur's Gate: Dark Alliance II (PAL)",
    "SLUS-20038": "Star Wars: Battlefront",
    "SLUS-21240": "Star Wars: Battlefront II",
    "SLUS-21077": "Burnout 3: Takedown",
    "SLUS-21197": "Burnout Revenge",
    "SLUS-20590": "Need for Speed: Underground",
    "SLUS-20811": "Need for Speed: Underground 2",
    "SLUS-20095": "Tony Hawk's Pro Skater 3",
    "SLUS-20480": "Tony Hawk's Pro Skater 4",
}


def detect_game_serial(filename: str, file_content: Optional[bytes] = None) -> str:
    """
    Attempt to detect a PS2 game serial from a filename (and optionally
    the first few KB of file content).

    Returns the normalised serial (e.g. ``"SLUS-20062"``), or an empty
    string if no serial is found.

    Normalisation: upper-case, separator always ``-`` (not ``_``).
    """
    # 1. Try the filename
    stem = Path(filename).stem
    serial = _parse_serial(stem)
    if serial:
        return serial

    # Also try the full path
    full = str(filename)
    serial = _parse_serial(full)
    if serial:
        return serial

    # 2. Optionally scan the first 4 KB of file content (e.g. text-based PNACH)
    if file_content:
        try:
            text = file_content[:4096].decode("utf-8", errors="ignore")
            serial = _parse_serial(text)
            if serial:
                return serial
        except Exception:
            pass

    return ""


def _parse_serial(text: str) -> str:
    """Extract and normalise the first PS2 serial found in *text*."""
    m = _SERIAL_PATTERN.search(text)
    if not m:
        return ""
    region = m.group(1).upper()
    number = m.group(2)
    return f"{region}-{number}"


def detect_game_serial_from_file(path: str) -> str:
    """
    Detect the PS2 game serial from a file path.
    Reads the first few KB of the file to look for embedded serial strings.
    """
    p = Path(path)
    # Try filename first (fast, no I/O)
    serial = detect_game_serial(str(p))
    if serial:
        return serial

    # Read file content for text-based files
    if p.is_file() and p.stat().st_size < 10 * 1024 * 1024:  # skip >10 MB
        try:
            with open(p, "rb") as f:
                content = f.read(4096)
            serial = detect_game_serial(str(p), content)
            if serial:
                return serial
        except OSError:
            pass

    return ""


def serial_to_display(serial: str) -> str:
    """
    Return a display string for a serial.
    If the serial is in the known-titles map, includes the game title.
    """
    if not serial:
        return ""
    title = _KNOWN_SERIALS.get(serial.upper(), "")
    if title:
        return f"{serial} — {title}"
    return serial


def normalise_serial(serial: str) -> str:
    """
    Normalise a PS2 serial to ``XXXX-NNNNN`` form (upper-case, dash separator).
    Returns the input unchanged if it doesn't match the expected pattern.
    """
    m = _SERIAL_PATTERN.search(serial)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    return serial.upper()


def lookup_game_title(serial: str) -> str:
    """
    Look up the game title for a given serial from the built-in registry.
    Returns an empty string if the serial is not recognised.
    """
    return _KNOWN_SERIALS.get(serial.upper(), "")


def all_known_serials() -> list[tuple[str, str]]:
    """Return a sorted list of (serial, title) tuples from the built-in registry."""
    return sorted(_KNOWN_SERIALS.items(), key=lambda x: x[0])
