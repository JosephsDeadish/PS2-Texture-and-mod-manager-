# PS2 Mod Manager

A modern, feature-rich desktop application for managing PCSX2 mods, texture packs, save files, PNACH patches, cover art, and cheats — all in one place.

---

## Features

### �� Texture Pack Manager
- Import and manage HD texture replacement packs
- Enable/disable individual packs without deleting them
- Set priority order — higher-priority packs win conflicts
- One-click **Deploy** to push enabled packs to PCSX2

### 🔧 PNACH Patch Manager
- Manage `.pnach` game patches (widescreen, 60fps, etc.)
- Enable/disable per-game patches independently
- Conflict detection between overlapping patches

### 🖼️ Cover Art Manager
- Store and deploy cover art for PCSX2's game browser
- Download cover art from **GameTDB** (free, by game ID)

### 💾 Memory Card & Save File Manager
- Browse all `.ps2` / `.mcd` memory card images in your memcards folder
- List individual saves within each card
- Export saves for backup

### ⚡ Cheats Manager
- Manage widescreen and other `.pnach`-format cheat files
- Works alongside the PNACH manager for full coverage

### 🌐 Browse & Download
- Curated links to community mod resources (GBAtemp, PCSX2 forums, GitHub, GameTDB)
- Download cover art by game ID directly from the app
- All sources are public and legal — no copyrighted content is redistributed

### ⚙️ Settings & Setup Wizard
- Guided setup wizard on first launch
- Auto-detection of PCSX2 config sub-folders (textures, covers, memcards, patches)
- All paths configurable individually

### 🔍 Conflict Detection
- Automatically detects when two enabled mods share the same files
- Visual conflict indicators per mod
- Resolution dialog: choose which mod wins, or allow both with a warning

---

## Requirements

- Python 3.10+
- PyQt6
- requests
- Pillow

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

---

## Project Structure

```
PS2-Texture-and-mod-manager-/
├── main.py                   # Entry point
├── requirements.txt
├── src/
│   ├── core/
│   │   ├── config_manager.py # Config load/save, PCSX2 path detection
│   │   ├── mod_manager.py    # Mod database + management logic
│   │   ├── memory_card.py    # PS2 memory card reader
│   │   └── downloader.py     # HTTPS download utilities
│   ├── models/
│   │   └── mod.py            # Data models (ModInfo, AppConfig, etc.)
│   └── ui/
│       ├── theme.py          # Dark theme stylesheet
│       ├── widgets.py        # Reusable UI widgets
│       ├── main_window.py    # Main application window
│       ├── setup_wizard.py   # First-run setup wizard
│       ├── dashboard.py      # Dashboard panel
│       ├── mod_panel.py      # Generic mod management panel
│       ├── memcard_panel.py  # Memory card panel
│       ├── browse_panel.py   # Browse & download panel
│       └── settings_panel.py # Settings panel
└── tests/
    └── test_core.py          # Unit tests for core logic
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Legal Notice

PS2 Mod Manager does not host, distribute, or include any copyrighted game content, BIOS files, or game ISOs. All mod resources are links to publicly available community content. Cover art is downloaded from [GameTDB](https://www.gametdb.com) which provides free cover images. Users are responsible for ensuring they have the right to use any mods, patches, or saves they manage with this tool.
