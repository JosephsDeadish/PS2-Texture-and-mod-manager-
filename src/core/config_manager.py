"""Configuration manager for PS2 Mod Manager."""

import json
import os
import sys
from pathlib import Path
from src.models.mod import AppConfig


def get_config_dir() -> Path:
    """Return platform-appropriate config directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(base) / "PS2ModManager"


def get_data_dir() -> Path:
    """Return platform-appropriate data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    data_dir = Path(base) / "PS2ModManager"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


CONFIG_FILE = get_config_dir() / "config.json"
MODS_DB_FILE = get_data_dir() / "mods.json"
THUMBNAILS_DIR = get_data_dir() / "thumbnails"


def ensure_dirs():
    """Create necessary directories."""
    get_config_dir().mkdir(parents=True, exist_ok=True)
    get_data_dir().mkdir(parents=True, exist_ok=True)
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    """Load configuration from disk."""
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return AppConfig()


def save_config(config: AppConfig):
    """Save configuration to disk."""
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)


def detect_pcsx2_paths(pcsx2_root: str) -> dict:
    """
    Given a PCSX2 install/config directory, auto-detect sub-folders.
    Returns a dict with keys: textures_path, pnach_path, cover_art_path,
    memcards_path, cheats_path.
    """
    root = Path(pcsx2_root)
    result = {}

    candidates = {
        "textures_path": [
            root / "textures",
            root / "Textures",
        ],
        "pnach_path": [
            root / "cheats",
            root / "Cheats",
            root / "patches",
        ],
        "cover_art_path": [
            root / "covers",
            root / "Covers",
            root / "cover art",
        ],
        "memcards_path": [
            root / "memcards",
            root / "MemoryCards",
            root / "memcards",
        ],
        "cheats_path": [
            root / "cheats_ws",
            root / "Cheats_WS",
            root / "cheats",
            root / "Cheats",
        ],
    }

    for key, paths in candidates.items():
        for p in paths:
            if p.exists():
                result[key] = str(p)
                break
        else:
            first = paths[0]
            result[key] = str(first)

    return result
