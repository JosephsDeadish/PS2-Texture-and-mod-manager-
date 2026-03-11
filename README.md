<p align="center">
  <img src="assets/icon_256.png" width="128" alt="PS2 Mod Manager icon"/>
</p>

<h1 align="center">PS2 Mod Manager</h1>

<p align="center">
  A modern, feature-rich desktop application for managing PCSX2 mods, texture packs,
  save files, PNACH patches, cover art, and cheats — all in one place.
</p>

<p align="center">
  <a href="https://www.patreon.com/c/DeadOnTheInside">
    <img src="https://img.shields.io/badge/Support-Patreon-f96854?logo=patreon&logoColor=white" alt="Support on Patreon"/>
  </a>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-blue" alt="Platform"/>
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/UI-PyQt6-41cd52" alt="PyQt6"/>
</p>

---

## ✨ Features

### 🎨 Texture Pack Manager
- Import HD texture replacement packs (ZIP, 7z, folder)
- Enable/disable individual packs without deleting them
- Set priority order — higher-priority packs win conflicts
- One-click **Deploy** to push enabled packs to PCSX2

### 🔧 PNACH Patch Manager
- Manage `.pnach` game patches (widescreen, 60fps, gameplay tweaks)
- Enable/disable per-game patches independently
- Conflict detection between overlapping patches

### 🖼️ Cover Art Manager
- Store and deploy cover art for PCSX2's game browser
- Download cover art from **GameTDB** (free, by game serial ID)

### 💾 Memory Card & Save File Manager
- Browse all `.ps2` / `.mcd` memory card images
- List and export individual saves
- **Import** a save dump back into a memory card
- **Copy** a save between memory card images
- **Backup** any card with a timestamped copy

### ⚡ Cheats Manager
- Manage widescreen and other `.pnach`-format cheat files

### 🌐 Browse & Download
- Curated catalogue of 11 community mod resources
- GBAtemp, Nexus Mods, PCSX2 Forums, GitHub, GameTDB, LaunchBox, GameFAQs, and more
- Async thumbnail loading per card
- Download cover art by game ID directly from GameTDB

### 🔍 Conflict Detection & Resolution
- Automatically detects when two enabled mods share the same files
- Visual conflict indicator per mod item
- Resolution dialog: choose which mod wins, or allow both with a warning

### 🔔 Automatic Update Checking
- Background check on startup for mods with a GitHub Releases source URL
- Status-bar notification when updates are found

### ⚙️ Settings & Setup Wizard
- Guided setup wizard on first launch
- Auto-detection of PCSX2 config sub-folders
- All paths configurable individually

### 🚀 Animated Splash Screen
- PS2 controller icon with pulsing glow ring and rotating accent arc
- Loading progress bar

---

## 🖥️ Screenshots

| Splash Screen | Dashboard | Memory Cards | Browse |
|---------------|-----------|--------------|--------|
| ![Splash](docs/screenshot_splash.png) | ![Dashboard](docs/screenshot_main.png) | ![Memory Cards](docs/screenshot_memcard.png) | ![Browse](docs/screenshot_browse.png) |

---

## 📋 Requirements

| Package | Version |
|---------|---------|
| Python | 3.10 + |
| PyQt6 | ≥ 6.6.0 |
| requests | ≥ 2.31.0 |
| Pillow | ≥ 10.0.0 |
| py7zr | ≥ 0.20.0 |

Install all runtime dependencies:

```bash
pip install -r requirements.txt
```

---

## 🚀 Running from Source

```bash
git clone https://github.com/JosephsDeadish/PS2-Texture-and-mod-manager-.git
cd PS2-Texture-and-mod-manager-
pip install -r requirements.txt
python main.py
```

---

## 📦 Building a Windows Executable

A pre-built Windows `.exe` is attached to every [GitHub Release](https://github.com/JosephsDeadish/PS2-Texture-and-mod-manager-/releases).

To build locally:

```bash
pip install -r requirements-build.txt   # adds pyinstaller
python assets/generate_icons.py         # regenerate icon files
pyinstaller PS2ModManager.spec --noconfirm
# Output: dist/PS2ModManager/PS2ModManager.exe
```

The CI workflow (`.github/workflows/build.yml`) builds automatically when a `v*` tag is pushed.

---

## 🧪 Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 🗂️ Project Structure

```
PS2-Texture-and-mod-manager-/
├── main.py                    # Entry point (splash + app init)
├── requirements.txt           # Runtime dependencies
├── requirements-build.txt     # + pyinstaller for EXE builds
├── PS2ModManager.spec         # PyInstaller spec
├── assets/
│   ├── icon.svg               # PS2 controller SVG icon (source)
│   ├── icon.ico               # Windows multi-resolution icon
│   ├── icon_{16,32,48,256}.png
│   └── generate_icons.py      # Renders SVG → PNG + ICO
├── src/
│   ├── core/
│   │   ├── assets.py          # Asset path helpers (dev + frozen)
│   │   ├── config_manager.py  # Config load/save, PCSX2 path detection
│   │   ├── mod_manager.py     # Mod database + management logic
│   │   ├── memory_card.py     # PS2 memory card read/write
│   │   ├── archive.py         # ZIP/7z extraction
│   │   ├── downloader.py      # HTTPS download utilities
│   │   └── updater.py         # Background mod update checker
│   ├── models/
│   │   └── mod.py             # Data models (ModInfo, AppConfig…)
│   └── ui/
│       ├── splash.py          # Animated startup splash screen
│       ├── theme.py           # Dark theme stylesheet
│       ├── widgets.py         # Reusable UI widgets
│       ├── main_window.py     # Main application window
│       ├── setup_wizard.py    # First-run setup wizard
│       ├── dashboard.py       # Dashboard panel
│       ├── mod_panel.py       # Generic mod management panel
│       ├── import_dialog.py   # Import/edit mod dialogs
│       ├── memcard_panel.py   # Memory card panel
│       ├── browse_panel.py    # Browse & download panel
│       └── settings_panel.py  # Settings panel
├── docs/
│   └── screenshot_main.png
└── tests/
    └── test_core.py           # Unit tests for core logic
```

---

## ⚖️ Legal Notice

PS2 Mod Manager does not host, distribute, or include any copyrighted game content,
BIOS files, or game ISOs. All mod resources are links to publicly available community
content. Cover art is downloaded from [GameTDB](https://www.gametdb.com) which provides
free cover images. Users are responsible for ensuring they have the right to use any
mods, patches, or saves they manage with this tool.

---

## ❤️ Support

If you enjoy PS2 Mod Manager, please consider supporting the developer:

[![Support on Patreon](https://img.shields.io/badge/Support-Patreon-f96854?logo=patreon&logoColor=white&style=for-the-badge)](https://www.patreon.com/c/DeadOnTheInside)
