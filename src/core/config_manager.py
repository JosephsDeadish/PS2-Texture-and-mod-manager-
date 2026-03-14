"""Configuration manager for PS2 Mod Manager."""

import json
import os
import sys
from pathlib import Path
from src.models.mod import AppConfig

# ---------------------------------------------------------------------------
# README content placed in the user_catalogue directory
# ---------------------------------------------------------------------------

_USER_CATALOGUE_README = """\
PS2 Mod Manager — User Catalogue
=================================

Drop custom JSON files into this folder to add your own catalogue entries.
Each JSON file must contain a top-level array of entry objects.

The "type" field controls which tab an entry appears in:
  texture_pack  — Texture Packs tab
  pnach         — PNACH Patches tab
  save_file     — Save Files tab
  cheat         — Cheats tab
  cover_art     — Cover Art tab

Required fields (every entry must have all of these):
  id            Unique identifier string (e.g. "my-pack-sly2-hd")
  name          Display name
  description   Short description shown in the UI
  author        Creator's name
  url           Link to the mod page / download page
  source        Source label (e.g. "GameFront", "Personal")
  game          Full game title (e.g. "Sly 2: Band of Thieves")
  game_serial   PS2 disc serial (e.g. "SCUS-97264")
  type          Mod type (see list above)

Optional fields (all have sensible defaults if omitted):
  context             ""
  author_url          ""
  is_hub              false
  nsfw                false
  thumbnail_url       ""
  tags                []
  download_action     ""
  direct_download_url ""
  upscale_tech        ""
  is_free             true
  requires_account    false
  is_complete         true
  size_label          ""   (e.g. "~250 MB")

Example entry:
[
  {
    "id": "my-pack-sly2-hd",
    "name": "Sly 2 HD Textures",
    "description": "Hand-crafted HD texture replacement for Sly 2.",
    "author": "YourName",
    "url": "https://example.com/sly2-hd",
    "source": "Personal",
    "game": "Sly 2: Band of Thieves",
    "game_serial": "SCUS-97264",
    "type": "texture_pack",
    "size_label": "~250 MB"
  }
]

Notes:
- IDs must be unique across all catalogue files (including built-in ones).
- Files with JSON parse errors are skipped (a warning is logged).
- Restart the application after adding or editing files here.
"""


def get_exe_dir() -> Path:
    """Return the directory that contains the application executable.

    * When running as a frozen PyInstaller bundle, this is the folder that
      contains the ``.exe`` / binary.
    * When running from source (``python main.py``), this is the project root
      directory (the folder containing ``main.py``).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller sets sys.executable to the frozen binary path
        return Path(sys.executable).parent
    # Running from source – two levels up from this file: src/core/ → src/ → project root
    return Path(__file__).resolve().parent.parent.parent


def get_config_dir() -> Path:
    """Return the config directory (next to the executable / project root)."""
    return get_exe_dir()


def get_data_dir() -> Path:
    """Return the user data directory (``data/`` subfolder next to the exe)."""
    data_dir = get_exe_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_user_catalogue_dir() -> Path:
    """Return the user catalogue directory (``user_catalogue/`` next to the exe).

    The directory is created automatically if it does not exist.  A
    ``README.txt`` explaining the JSON format is written on first creation so
    users know exactly what to put there.
    """
    user_cat_dir = get_exe_dir() / "user_catalogue"
    user_cat_dir.mkdir(parents=True, exist_ok=True)
    readme = user_cat_dir / "README.txt"
    if not readme.exists():
        readme.write_text(_USER_CATALOGUE_README, encoding="utf-8")
    return user_cat_dir


CONFIG_FILE = get_config_dir() / "config.json"
MODS_DB_FILE = get_data_dir() / "mods.json"
THUMBNAILS_DIR = get_data_dir() / "thumbnails"
LOAD_ORDER_FILE = get_data_dir() / "load_order.json"
PROFILES_FILE = get_data_dir() / "profiles.json"


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

