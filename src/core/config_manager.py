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

    Uses :func:`src.core.pcsx2_layout.detect_pcsx2_subfolders` for the full
    platform-aware detection.  Returns a dict with keys:
    ``textures_path``, ``pnach_path``, ``cover_art_path``, ``memcards_path``,
    ``cheats_path``, ``partial_textures_path``.
    """
    from src.core.pcsx2_layout import detect_pcsx2_subfolders
    return detect_pcsx2_subfolders(pcsx2_root)


def auto_detect_pcsx2() -> str:
    """
    Probe all known platform-specific PCSX2 install locations and return the
    first valid config directory found, or ``""`` if PCSX2 cannot be located.

    Delegates to :func:`src.core.pcsx2_layout.auto_detect_pcsx2`.
    """
    from src.core.pcsx2_layout import auto_detect_pcsx2 as _detect
    return _detect()

