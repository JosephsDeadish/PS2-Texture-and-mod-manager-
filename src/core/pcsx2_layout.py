"""PCSX2 folder hierarchy knowledge and utilities.

This module is the single source of truth for:

* The **PCSX2 directory structure** — what every sub-folder is for.
* **Auto-detecting** PCSX2 across Windows, Linux (native / Snap / Flatpak /
  AppImage), and macOS — including both legacy wxWidgets and modern Qt builds.
* **Resolving the correct deployment target** for each :class:`ModType` given
  the user's :class:`AppConfig`.
* **Scaffolding** the full PCSX2 folder tree so fresh installs work out-of-the-box.

PCSX2 Folder Hierarchy
-----------------------
::

    <pcsx2_root>/
    ├── bios/               PS2 BIOS images (required by emulator)
    ├── cheats/             PNACH cheat/patch files (game CRC as filename)
    ├── cheats_ws/          Widescreen PNACH patches
    ├── covers/             Game cover art (SERIAL.png, e.g. SLUS-20062.png)
    ├── inis/               Emulator configuration INI files
    ├── logs/               Log files (auto-created by PCSX2)
    ├── memcards/           PS2 memory card images (.ps2 / .mcd)
    ├── patches/            Additional game patches / cheat codes (alternate)
    ├── savestates/         Save state files
    ├── screenshots/        In-game screenshots (snaps/)
    └── textures/           Texture replacement packs
        └── <SERIAL>/       One folder per game, named after its disc serial
            ├── replacements/   Full / partial texture replacements (PNG/DDS)
            └── dumps/          Texture dumps captured from the emulator

Texture pack sub-hierarchy
--------------------------
PCSX2 looks for replacement textures under::

    textures/<SERIAL>/replacements/<filename>

where *<SERIAL>* is the disc serial in the normalised ``XXXX-NNNNN`` form
(e.g. ``SLUS-20062``).  Texture packs installed by this manager are stored
as a folder named after the pack's UUID (mod ID) inside the managed storage
location, and **deployed** (i.e. copied / hard-linked) into the correct
``textures/<SERIAL>/replacements/`` folder when enabled.

Usage::

    from src.core.pcsx2_layout import (
        PCSX2_HIERARCHY, auto_detect_pcsx2, get_deploy_path,
        create_pcsx2_directories, folder_description,
    )
    from src.models.mod import ModType

    root = auto_detect_pcsx2()   # -> "/home/user/.config/PCSX2" or ""
    path = get_deploy_path(config, ModType.TEXTURE_PACK)  # -> textures dir
    create_pcsx2_directories(root)  # scaffold missing dirs
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.models.mod import ModType


# ---------------------------------------------------------------------------
# PCSX2 folder hierarchy — name → description
# ---------------------------------------------------------------------------

#: Maps every standard PCSX2 sub-folder name to a human-readable description.
PCSX2_HIERARCHY: Dict[str, str] = {
    "bios": "PS2 BIOS images required by the emulator",
    "cheats": "PNACH cheat/patch files (named after game CRC, e.g. F0A235B4.pnach)",
    "cheats_ws": "Widescreen PNACH patch files",
    "covers": "Game cover art images (SERIAL.png, e.g. SLUS-20062.png)",
    "inis": "Emulator configuration INI files",
    "logs": "Emulator log files",
    "memcards": "PS2 memory card images (.ps2 / .mcd)",
    "patches": "Additional game patches / cheat codes (alternate cheats folder)",
    "savestates": "Save state files",
    "screenshots": "In-game screenshots captured by PCSX2",
    "textures": (
        "Texture replacement packs.  "
        "Layout: textures/<SERIAL>/replacements/<file> "
        "and textures/<SERIAL>/dumps/<file>"
    ),
}

#: Sub-folders created inside ``textures/<SERIAL>/`` for each game.
TEXTURE_GAME_SUBFOLDERS: tuple[str, ...] = ("replacements", "dumps")

# ---------------------------------------------------------------------------
# PCSX2 user guidance — enabling cheats and texture loading
# ---------------------------------------------------------------------------

#: Step-by-step instructions for enabling PNACH cheats/patches in PCSX2 Qt (v1.7+).
PCSX2_ENABLE_CHEATS_STEPS: tuple[str, ...] = (
    "Right-click the game in the PCSX2 game list and choose 'Properties'.",
    "Select the 'Patches' tab (or 'Cheats' tab in older builds).",
    "Tick 'Enable Cheats' at the top of the tab.",
    "Click 'OK' to save, then launch the game — patches will be applied on boot.",
)

#: Plain-English summary shown near cheat/PNACH features.
PCSX2_CHEATS_HINT: str = (
    "⚠️  PCSX2 does not apply PNACH codes by default.  "
    "To activate installed patches or cheats, right-click the game in PCSX2, "
    "open 'Properties', go to the 'Patches' tab, and tick 'Enable Cheats'.  "
    "Restart the game after making this change."
)

#: Step-by-step instructions for enabling texture replacement in PCSX2 Qt (v1.7+).
PCSX2_ENABLE_TEXTURES_STEPS: tuple[str, ...] = (
    "Right-click the game in the PCSX2 game list and choose 'Properties'.",
    "Select the 'Graphics' tab.",
    "Under 'Texture Replacement', tick 'Load Textures'.",
    "Optionally tick 'Precache Textures' to reduce in-game stutter.",
    "Click 'OK' to save, then launch the game — replacement textures will load.",
)

#: Plain-English summary shown near texture-pack features.
PCSX2_TEXTURES_HINT: str = (
    "⚠️  PCSX2 does not load replacement textures by default.  "
    "To activate an installed texture pack, right-click the game in PCSX2, "
    "open 'Properties', go to the 'Graphics' tab, and tick 'Load Textures'.  "
    "Restart the game after making this change."
)

#: Step-by-step instructions for dumping textures in PCSX2 Qt (v1.7+).
PCSX2_DUMP_TEXTURES_STEPS: tuple[str, ...] = (
    "Right-click the game in the PCSX2 game list and choose 'Properties'.",
    "Select the 'Graphics' tab.",
    "Under 'Texture Replacement', tick 'Dump Textures'.",
    "Launch the game and navigate to areas whose textures you want to dump.",
    "Exit PCSX2 — dumped textures will be in textures/<SERIAL>/dumps/.",
    "Disable 'Dump Textures' again when finished to avoid large dumps.",
)


def get_cheats_guidance() -> dict:
    """Return structured guidance for enabling PNACH cheats in PCSX2.

    Returns
    -------
    dict
        Keys: ``"hint"`` (str), ``"steps"`` (list[str]).
    """
    return {
        "hint": PCSX2_CHEATS_HINT,
        "steps": list(PCSX2_ENABLE_CHEATS_STEPS),
    }


def get_textures_guidance() -> dict:
    """Return structured guidance for enabling texture loading in PCSX2.

    Returns
    -------
    dict
        Keys: ``"hint"`` (str), ``"steps"`` (list[str]).
    """
    return {
        "hint": PCSX2_TEXTURES_HINT,
        "steps": list(PCSX2_ENABLE_TEXTURES_STEPS),
    }


def get_dump_textures_guidance() -> dict:
    """Return structured guidance for dumping textures from PCSX2.

    Returns
    -------
    dict
        Keys: ``"hint"`` (str), ``"steps"`` (list[str]).
    """
    return {
        "hint": (
            "ℹ️  To create a new texture pack, first dump textures from PCSX2.  "
            "Enable 'Dump Textures' in game properties, play the game, then "
            "edit the dumped files and place them in the replacements folder."
        ),
        "steps": list(PCSX2_DUMP_TEXTURES_STEPS),
    }


# ---------------------------------------------------------------------------
# ModType → PCSX2 folder mapping
# ---------------------------------------------------------------------------

#: Maps each ModType to the AppConfig attribute name that holds its target path.
_MOD_TYPE_TO_CONFIG_ATTR: Dict[ModType, str] = {
    ModType.TEXTURE_PACK: "textures_path",
    ModType.PNACH:        "pnach_path",
    ModType.COVER_ART:    "cover_art_path",
    ModType.SAVE_FILE:    "memcards_path",
    ModType.CHEAT:        "cheats_path",
}

#: Default PCSX2 sub-folder for each ModType (relative to pcsx2 root).
_MOD_TYPE_TO_SUBFOLDER: Dict[ModType, str] = {
    ModType.TEXTURE_PACK: "textures",
    ModType.PNACH:        "cheats",
    ModType.COVER_ART:    "covers",
    ModType.SAVE_FILE:    "memcards",
    ModType.CHEAT:        "cheats_ws",
}


def folder_description(folder_name: str) -> str:
    """Return the human-readable description for a PCSX2 sub-folder name."""
    return PCSX2_HIERARCHY.get(folder_name, "")


def get_deploy_path(config, mod_type: ModType) -> str:
    """
    Return the correct filesystem path for deploying mods of *mod_type*.

    Reads the path from *config* (an :class:`~src.models.mod.AppConfig`).
    Falls back to ``""`` if the path is not configured.

    Example::

        path = get_deploy_path(config, ModType.TEXTURE_PACK)
        # -> "/home/user/.config/PCSX2/textures"
    """
    attr = _MOD_TYPE_TO_CONFIG_ATTR.get(mod_type, "")
    if attr:
        return getattr(config, attr, "") or ""
    return ""


def get_texture_replacements_path(textures_root: str, serial: str) -> str:
    """
    Return the PCSX2 texture replacement path for a specific game serial.

    This is the folder that PCSX2 watches for texture replacements::

        <textures_root>/<serial>/replacements/

    Example::

        get_texture_replacements_path("/data/pcsx2/textures", "SLUS-20062")
        # -> "/data/pcsx2/textures/SLUS-20062/replacements"
    """
    if not textures_root or not serial:
        return ""
    return str(Path(textures_root) / serial / "replacements")


def get_texture_dumps_path(textures_root: str, serial: str) -> str:
    """Return the PCSX2 texture dump path for a game serial."""
    if not textures_root or not serial:
        return ""
    return str(Path(textures_root) / serial / "dumps")


# ---------------------------------------------------------------------------
# PCSX2 auto-detection
# ---------------------------------------------------------------------------

def _candidate_paths() -> List[Path]:
    """
    Return an ordered list of candidate PCSX2 config/data directories to probe,
    covering every major platform variant.
    """
    home = Path.home()
    candidates: List[Path] = []

    if sys.platform == "win32":
        # Modern PCSX2 Qt (1.7+) stores config in AppData\Roaming\PCSX2
        appdata = Path(
            __import__("os").environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        )
        local = Path(
            __import__("os").environ.get(
                "LOCALAPPDATA", str(home / "AppData" / "Local")
            )
        )
        docs = home / "Documents"
        candidates += [
            appdata / "PCSX2",           # Qt PCSX2 1.7+
            local / "PCSX2",             # Some installations
            docs / "PCSX2",              # Older wxWidgets PCSX2
            Path("C:/Program Files/PCSX2"),
            Path("C:/Program Files (x86)/PCSX2"),
        ]

    elif sys.platform == "darwin":
        candidates += [
            home / "Library" / "Application Support" / "PCSX2",
            home / ".config" / "PCSX2",
            Path("/Applications/PCSX2.app/Contents/Resources"),
        ]

    else:  # Linux / BSD / etc.
        candidates += [
            # Snap (Ubuntu default install)
            home / "snap" / "pcsx2" / "current" / ".config" / "PCSX2",
            home / "snap" / "pcsx2" / "current" / ".local" / "share" / "PCSX2",
            # Flatpak
            home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2",
            home / ".var" / "app" / "net.pcsx2.PCSX2" / "data" / "PCSX2",
            # AppImage / distro package / native build
            home / ".config" / "PCSX2",
            home / ".local" / "share" / "PCSX2",
            # Legacy wxWidgets paths
            home / ".pcsx2",
            Path("/usr/share/pcsx2"),
            Path("/opt/pcsx2"),
        ]

    return candidates


def auto_detect_pcsx2() -> str:
    """
    Return the path of the first existing PCSX2 config directory found, or
    ``""`` if none can be found on this machine.

    The function probes all known platform-specific candidate locations:

    * **Windows**: ``%APPDATA%\\PCSX2``, ``%LOCALAPPDATA%\\PCSX2``,
      ``Documents\\PCSX2``, ``C:\\Program Files\\PCSX2``
    * **Linux Snap**: ``~/snap/pcsx2/current/.config/PCSX2``
    * **Linux Flatpak**: ``~/.var/app/net.pcsx2.PCSX2/config/PCSX2``
    * **Linux native/AppImage**: ``~/.config/PCSX2``, ``~/.local/share/PCSX2``
    * **Legacy wxWidgets**: ``~/.pcsx2``
    * **macOS**: ``~/Library/Application Support/PCSX2``

    The candidate that contains a ``bios/``, ``textures/``, ``cheats/``, or
    ``covers/`` subdirectory is preferred over a plain-existence match.
    """
    candidates = _candidate_paths()
    scored: List[tuple[int, Path]] = []

    for c in candidates:
        if not c.exists():
            continue
        # Score by how many recognisable PCSX2 sub-folders are present
        score = sum(
            1 for sub in ("bios", "textures", "cheats", "covers", "memcards", "inis")
            if (c / sub).exists()
        )
        scored.append((score, c))

    if not scored:
        return ""

    # Return the candidate with the highest score (most PCSX2 sub-dirs)
    scored.sort(key=lambda x: x[0], reverse=True)
    return str(scored[0][1])


def detect_pcsx2_subfolders(pcsx2_root: str) -> Dict[str, str]:
    """
    Given a PCSX2 root directory, return a dict of all relevant sub-folder
    paths (creating fallback defaults for missing ones).

    Keys returned:
        ``textures_path``, ``pnach_path``, ``cover_art_path``,
        ``memcards_path``, ``cheats_path``, ``partial_textures_path``

    Missing folders are returned as their canonical expected path so the
    caller can create them if desired.
    """
    root = Path(pcsx2_root)
    # Map config-attribute → list of candidate sub-folder names in priority order
    folder_candidates: Dict[str, List[str]] = {
        "textures_path":         ["textures", "Textures"],
        "pnach_path":            ["cheats", "Cheats", "patches", "Patches"],
        "cover_art_path":        ["covers", "Covers", "cover art"],
        "memcards_path":         ["memcards", "MemoryCards"],
        "cheats_path":           ["cheats_ws", "Cheats_WS", "cheats", "Cheats"],
        "partial_textures_path": ["textures", "Textures"],  # same root, sub-structured by serial
    }

    result: Dict[str, str] = {}
    for key, names in folder_candidates.items():
        found = ""
        for name in names:
            p = root / name
            if p.exists():
                found = str(p)
                break
        if not found:
            # Use the first (canonical) name as the default even if it doesn't exist
            found = str(root / names[0])
        result[key] = found

    return result


# ---------------------------------------------------------------------------
# Directory scaffolding
# ---------------------------------------------------------------------------

def create_pcsx2_directories(pcsx2_root: str) -> List[str]:
    """
    Create the standard PCSX2 sub-folder tree under *pcsx2_root*.

    Only creates missing directories; existing ones are left untouched.
    Returns a list of paths that were newly created.

    This is called during automatic setup when the user opts to let PS2 Mod
    Manager configure their PCSX2 folder structure.
    """
    root = Path(pcsx2_root)
    root.mkdir(parents=True, exist_ok=True)

    created: List[str] = []
    for folder in PCSX2_HIERARCHY:
        p = root / folder
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))

    return created


def ensure_texture_game_dirs(textures_root: str, serial: str) -> Dict[str, str]:
    """
    Create (if missing) the per-game texture sub-folders for *serial*::

        <textures_root>/<serial>/replacements/
        <textures_root>/<serial>/dumps/

    Returns a dict with keys ``"replacements"`` and ``"dumps"`` pointing to
    the created/existing paths.
    """
    base = Path(textures_root) / serial
    result: Dict[str, str] = {}
    for sub in TEXTURE_GAME_SUBFOLDERS:
        p = base / sub
        p.mkdir(parents=True, exist_ok=True)
        result[sub] = str(p)
    return result
