"""Browse & Download panel — discover mods from public sources.

Features:
- Tabbed browsing per mod type (All / Textures / PNACH / Covers / Saves / Cheats)
- Live search across catalogue entries (name, game, author, tags)
- Source filter dropdown (filter by hosting site)
- Author filter / favorite authors (❤ toggle to mark favorite)
- "Download from URL" dialog with Google Drive conversion
- Rich catalogue entries with upscale info, author links, context
"""

import os
import threading
import tempfile
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QDialog,
    QProgressBar,
    QSizePolicy,
    QCheckBox,
)

from src.core.config_manager import THUMBNAILS_DIR, save_config
from src.core.downloader import (
    DownloadError,
    download_file,
    download_pcsx2_widescreen_patch,
    list_pcsx2_widescreen_patches,
    search_pcsx2_patches_by_crc,
)
from src.models.mod import AppConfig, ModType
from src.ui.base_panel import BasePanel


# ---------------------------------------------------------------------------
# Catalogue — expanded with Lovers Lab, PS2-Home, PSX-Place, Archive.org, etc.
# ---------------------------------------------------------------------------

CATALOGUE: List[dict] = [
    # ── Texture Packs ─────────────────────────────────────────────────────────
    {
        "id": "pcsx2_wiki_textures",
        "name": "PCSX2 Texture Replacement Guide",
        "description": (
            "The official PCSX2 wiki explains how to create and install HD texture "
            "replacement packs. Browse community-made packs linked from the wiki."
        ),
        "context": "Official guide — good starting point for understanding texture replacement workflow.",
        "author": "PCSX2 Community",
        "author_url": "https://wiki.pcsx2.net",
        "url": "https://wiki.pcsx2.net/Texture_Replacement",
        "type": ModType.TEXTURE_PACK,
        "source": "PCSX2",
        "game": "",
        "thumbnail_url": "https://wiki.pcsx2.net/images/pcsx2-icon.png",
        "tags": ["guide", "official"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "gbatemp_textures",
        "name": "GBAtemp PS2 Texture Packs",
        "description": (
            "GBAtemp.net hosts community-uploaded HD texture packs for PS2 games. "
            "Browse and download individual packs for your favourite titles."
        ),
        "context": "Large community forum — authors often include upscale info and recommended settings in their posts.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/tags/ps2-texture-pack/",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "",
        "thumbnail_url": "https://gbatemp.net/styles/gbatemp/logo.png",
        "tags": ["community", "hd", "gbatemp"],
        "download_action": "",
        "upscale_tech": "Various (xBRZ, ESRGAN, Waifu2x)",
    },
    {
        "id": "loverslab_ps2",
        "name": "LoversLab — PS2 Texture Mods",
        "description": (
            "LoversLab is a major modding community with a growing PS2 / PCSX2 "
            "section. Authors publish HD texture packs with detailed descriptions, "
            "upscaling methodology, and recommended PCSX2 settings."
        ),
        "context": (
            "Authors on LoversLab often detail their upscale technique (ESRGAN model used, "
            "resolution), provide recommended PCSX2 graphic settings, and link to their "
            "other work. Check the description of each post for this information."
        ),
        "author": "LoversLab Community",
        "author_url": "https://www.loverslab.com",
        "url": "https://www.loverslab.com/search/#q=ps2+texture&t=files",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "",
        "thumbnail_url": "",
        "tags": ["community", "hd", "loverslab", "esrgan"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ / Manual",
    },
    {
        "id": "nexusmods_ps2",
        "name": "Nexus Mods — PS2 / PCSX2",
        "description": (
            "Nexus Mods PS2 section — community-contributed texture packs and mods. "
            "Each file page includes author notes on upscale method and settings."
        ),
        "context": "Nexus enforces a structured mod-page format so author-recommended settings are usually in the description.",
        "author": "Nexus Mods",
        "author_url": "https://www.nexusmods.com",
        "url": "https://www.nexusmods.com/pcsx2",
        "type": ModType.TEXTURE_PACK,
        "source": "Nexus Mods",
        "game": "",
        "thumbnail_url": "https://www.nexusmods.com/favicon.ico",
        "tags": ["community", "textures", "hd", "nexus"],
        "download_action": "",
        "upscale_tech": "Various",
    },
    {
        "id": "ps2_home_textures",
        "name": "PS2-Home — PS2 HD Textures",
        "description": (
            "PS2-Home.com is a dedicated PS2 community site hosting mods, texture "
            "packs, and patches. Browse the Downloads section for texture packs."
        ),
        "context": "PS2-focused community — most uploads include author names and game compatibility notes.",
        "author": "PS2-Home Community",
        "author_url": "https://www.ps2-home.com",
        "url": "https://www.ps2-home.com/forum/viewforum.php?f=50",
        "type": ModType.TEXTURE_PACK,
        "source": "PS2-Home",
        "game": "",
        "thumbnail_url": "",
        "tags": ["community", "hd", "ps2-home"],
        "download_action": "",
        "upscale_tech": "Various",
    },
    {
        "id": "psx_place_textures",
        "name": "PSX-Place — PS2 Texture Packs",
        "description": (
            "PSX-Place hosts PS2 mods, patches and texture packs. "
            "The dedicated PS2 section has author-credited releases with changelogs."
        ),
        "context": "PlayStation-focused site — HD texture packs and mods with version history and author attribution.",
        "author": "PSX-Place Community",
        "author_url": "https://www.psx-place.com",
        "url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "type": ModType.TEXTURE_PACK,
        "source": "PSX-Place",
        "game": "",
        "thumbnail_url": "",
        "tags": ["community", "hd", "psx-place"],
        "download_action": "",
        "upscale_tech": "Various",
    },
    {
        "id": "reddit_ps2_textures",
        "name": "r/ps2 — Mods & Textures",
        "description": (
            "Reddit r/ps2 community shares texture packs, mods, and patches. "
            "Authors often post links to Google Drive or MEGA downloads."
        ),
        "context": "Author posts often link to external hosting (Google Drive, MEGA). Use the Download from URL button to install directly.",
        "author": "Reddit r/ps2",
        "author_url": "https://www.reddit.com/r/ps2",
        "url": "https://www.reddit.com/r/ps2/search/?q=texture+pack&sort=new",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "",
        "thumbnail_url": "https://www.redditstatic.com/desktop2x/img/favicon/favicon-32x32.png",
        "tags": ["community", "hd", "reddit"],
        "download_action": "",
        "upscale_tech": "Various",
    },
    # ── PNACH / Patches ───────────────────────────────────────────────────────
    {
        "id": "pcsx2_widescreen_github",
        "name": "PCSX2 Widescreen Patches (GitHub)",
        "description": (
            "Official collection of 16:9 widescreen PNACH patches for hundreds "
            "of PS2 games, maintained by the PCSX2 team on GitHub."
        ),
        "context": "Every patch file is named by game CRC. Use the PNACH manager to import directly.",
        "author": "PCSX2 Team",
        "author_url": "https://github.com/PCSX2",
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "official", "open-source"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "pcsx2_cheats_forum",
        "name": "PCSX2 Cheat / PNACH Archive",
        "description": (
            "Community-maintained PNACH cheat files for PS2 games, "
            "including widescreen, 60fps patches, and gameplay cheats."
        ),
        "context": "Forum thread links to community-submitted PNACH files. Author attribution included in thread posts.",
        "author": "PCSX2 Forums",
        "author_url": "https://forums.pcsx2.net",
        "url": "https://forums.pcsx2.net/Thread-PNACH-Patches",
        "type": ModType.PNACH,
        "source": "PCSX2",
        "game": "",
        "thumbnail_url": "https://pcsx2.net/favicon.ico",
        "tags": ["patches", "pnach", "widescreen", "60fps"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_patches",
        "name": "PS2Wide — Widescreen Hack DB",
        "description": (
            "Community database of widescreen and HD resolution hacks for "
            "hundreds of PS2 games in PNACH format."
        ),
        "context": "Specialised in widescreen hacks — includes aspect ratio corrections and HUD fixes.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "",
        "thumbnail_url": "",
        "tags": ["widescreen", "resolution", "pnach"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "gbatemp_pnach",
        "name": "GBAtemp PS2 Patches & Cheats",
        "description": (
            "GBAtemp.net also hosts PNACH cheat files and game patches for PS2. "
            "Search for your game to find community-submitted patches."
        ),
        "context": "Authors include game CRC, version notes, and sometimes recommended companion mods.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/3519/?q=pnach&t=file_update",
        "type": ModType.PNACH,
        "source": "GBAtemp",
        "game": "",
        "thumbnail_url": "https://gbatemp.net/styles/gbatemp/logo.png",
        "tags": ["patches", "pnach", "gbatemp"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Cover Art ─────────────────────────────────────────────────────────────
    {
        "id": "gametdb_covers",
        "name": "GameTDB Cover Art (PS2)",
        "description": (
            "GameTDB.com provides free PS2 cover art by game serial/ID. "
            "Click 'Download Cover by ID' to fetch cover art for any PS2 game."
        ),
        "context": "Comprehensive cover art database — uses game serial (SLUS/SCUS) as the lookup key.",
        "author": "GameTDB",
        "author_url": "https://www.gametdb.com",
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "source": "GameTDB",
        "game": "All Games",
        "thumbnail_url": "https://www.gametdb.com/favicon.ico",
        "tags": ["covers", "art", "official"],
        "download_action": "cover_by_id",
        "upscale_tech": "",
    },
    {
        "id": "launchbox_art",
        "name": "LaunchBox Games Database",
        "description": (
            "LaunchBox hosts a large database of PS2 game artwork including "
            "box fronts, backs, screenshots and more — community-contributed."
        ),
        "context": "High-resolution scans and recreations. Good for box-art replacements.",
        "author": "LaunchBox Community",
        "author_url": "https://www.launchbox-app.com",
        "url": "https://gamesdb.launchbox-app.com/platforms/games/11",
        "type": ModType.COVER_ART,
        "source": "LaunchBox",
        "game": "",
        "thumbnail_url": "https://www.launchbox-app.com/favicon.ico",
        "tags": ["covers", "artwork", "community"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "archive_org_covers",
        "name": "Internet Archive — PS2 Cover Art",
        "description": (
            "The Internet Archive hosts scanned and digital PS2 box art and manuals. "
            "A great source for rare regional covers."
        ),
        "context": "Scanned physical media — highest-quality lossless images for many regional variants.",
        "author": "Internet Archive",
        "author_url": "https://archive.org",
        "url": "https://archive.org/search?query=PS2+cover+art&mediatype=image",
        "type": ModType.COVER_ART,
        "source": "Archive.org",
        "game": "",
        "thumbnail_url": "",
        "tags": ["covers", "archive", "scanned"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Save Files ────────────────────────────────────────────────────────────
    {
        "id": "gamefaqs_saves",
        "name": "GameFAQs PS2 Save Files",
        "description": (
            "GameFAQs hosts community-submitted PS2 save files for hundreds of games. "
            "Download saves to pick up where someone left off."
        ),
        "context": "Save files listed by game; most include region info and save slot description.",
        "author": "GameFAQs Community",
        "author_url": "https://gamefaqs.gamespot.com",
        "url": "https://gamefaqs.gamespot.com/ps2/category/929-saves",
        "type": ModType.SAVE_FILE,
        "source": "GameFAQs",
        "game": "",
        "thumbnail_url": "https://gamefaqs.gamespot.com/favicon.ico",
        "tags": ["saves", "community"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2saves_com",
        "name": "PS2 Saves Database",
        "description": (
            "Collection of PS2 save files shared by the community, organised by "
            "game title. Download and import with the Memory Card manager."
        ),
        "context": "Organised by game title with author credits. Import using the Memory Card panel.",
        "author": "PS2Saves Community",
        "author_url": "https://ps2saves.com",
        "url": "https://ps2saves.com",
        "type": ModType.SAVE_FILE,
        "source": "PS2Saves",
        "game": "",
        "thumbnail_url": "",
        "tags": ["saves", "community"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Cheats ────────────────────────────────────────────────────────────────
    {
        "id": "pcsx2_cheatdb",
        "name": "PCSX2 Cheat Database (GitHub)",
        "description": (
            "Community-maintained cheat archive for PCSX2. "
            "Contains WideScreen, 60FPS, and gameplay cheats in PNACH format."
        ),
        "context": "Well-organised by game CRC. Each file is labelled with CRC and game name for easy identification.",
        "author": "PCSX2 Community",
        "author_url": "https://github.com/PCSX2",
        "url": "https://github.com/PCSX2/cheatdb",
        "type": ModType.CHEAT,
        "source": "GitHub",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["cheats", "pnach", "official"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "codejunkies_ps2",
        "name": "Code Junkies PS2 Cheats",
        "description": (
            "Code Junkies maintains a database of PS2 cheat codes that can be "
            "converted to PNACH format for use with PCSX2."
        ),
        "context": "ActionReplay / GameShark format — the app imports and converts them to PNACH automatically.",
        "author": "Code Junkies",
        "author_url": "https://www.codejunkies.com",
        "url": "https://www.codejunkies.com/ps2/",
        "type": ModType.CHEAT,
        "source": "CodeJunkies",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "codes"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "psx_place_cheats",
        "name": "PSX-Place — PS2 Cheats & Patches",
        "description": (
            "PSX-Place hosts PS2 cheat codes and PNACH patches contributed by the community."
        ),
        "context": "PS2-focused site with version-tagged releases and author attribution.",
        "author": "PSX-Place Community",
        "author_url": "https://www.psx-place.com",
        "url": "https://www.psx-place.com/resources/categories/ps2-cheats.19/",
        "type": ModType.CHEAT,
        "source": "PSX-Place",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "pnach", "psx-place"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Patreon creators ─────────────────────────────────────────────────────
    {
        "id": "patreon_ps2_textures",
        "name": "PS2 Texture Creators on Patreon",
        "description": (
            "Several PS2 texture artists publish their HD packs exclusively on Patreon. "
            "Search Patreon for 'PS2 texture' or 'PCSX2' to find active creators. "
            "Most offer free tiers with public releases and paid tiers for early access."
        ),
        "context": (
            "Patreon creators typically document their upscaling technique (ESRGAN model, "
            "resolution multiplier), provide recommended PCSX2 graphic plugin settings, "
            "and link to their other works. Check the About section of each creator's page."
        ),
        "author": "Various Patreon Creators",
        "author_url": "https://www.patreon.com/search?q=ps2+texture",
        "url": "https://www.patreon.com/search?q=ps2+texture+pcsx2",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "hd", "esrgan", "community"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ / Manual",
    },
    {
        "id": "deadontheinside_patreon",
        "name": "DeadOnTheInside — PS2 Mods & Tools",
        "description": (
            "Support the developer of PS2 Mod Manager on Patreon! "
            "Patrons get early access to new features, exclusive mod packs, "
            "and direct input on the roadmap."
        ),
        "context": (
            "Your support keeps PS2 Mod Manager free and actively maintained. "
            "Patreon members also get priority support and early builds."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "support", "dev"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Game-Specific Texture Packs ───────────────────────────────────────────
    {
        "id": "spyro_etd_textures",
        "name": "Spyro: Enter the Dragonfly — HD Textures",
        "description": (
            "Community HD texture pack for Spyro: Enter the Dragonfly (SLUS-20309). "
            "Browse GBAtemp and LoversLab for upscaled packs using ESRGAN and xBRZ."
        ),
        "context": "Search for 'Spyro Enter Dragonfly texture' on GBAtemp or LoversLab for community uploads.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=spyro+ps2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Spyro: Enter the Dragonfly",
        "thumbnail_url": "",
        "tags": ["spyro", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "crash_woc_textures",
        "name": "Crash Bandicoot: Wrath of Cortex — HD Textures",
        "description": (
            "HD texture replacement packs for Crash Bandicoot: The Wrath of Cortex (SLUS-20238). "
            "Community-made packs with ESRGAN-upscaled character and environment textures."
        ),
        "context": "Check GBAtemp and the PCSX2 forums for Crash texture packs — authors often list upscale model and settings.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=crash+bandicoot+ps2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Crash Bandicoot: Wrath of Cortex",
        "thumbnail_url": "",
        "tags": ["crash", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "gow1_textures",
        "name": "God of War — HD Texture Pack",
        "description": (
            "HD texture replacements for God of War (SCUS-97399). "
            "Community authors have produced high-quality upscales of Kratos, environments, and enemies."
        ),
        "context": "LoversLab and GBAtemp have several GoW packs. Authors typically note recommended PCSX2 renderer (OpenGL/Vulkan).",
        "author": "LoversLab Community",
        "author_url": "https://www.loverslab.com",
        "url": "https://www.loverslab.com/search/#q=god+of+war+ps2+texture&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "God of War",
        "thumbnail_url": "",
        "tags": ["god-of-war", "gow", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "ffx_textures",
        "name": "Final Fantasy X — HD Texture Replacements",
        "description": (
            "Community HD texture packs for Final Fantasy X (SLUS-20312). "
            "Browse packs covering characters, menus, FMV upscales and environment retextures."
        ),
        "context": "Several authors on GBAtemp and PCSX2 forums have published FFX packs; check thread dates for compatibility with recent PCSX2 nightly builds.",
        "author": "PCSX2 Community",
        "author_url": "https://forums.pcsx2.net",
        "url": "https://forums.pcsx2.net/search?q=final+fantasy+x+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "PCSX2 Forums",
        "game": "Final Fantasy X",
        "thumbnail_url": "",
        "tags": ["final-fantasy", "ffx", "hd", "jrpg", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / Waifu2x",
    },
    {
        "id": "kh1_textures",
        "name": "Kingdom Hearts — HD Texture Pack",
        "description": (
            "HD texture replacements for Kingdom Hearts (SLUS-20370). "
            "Upscaled character, world, and UI textures from the community."
        ),
        "context": "Check GBAtemp and LoversLab for KH texture packs. Many authors use ESRGAN with anime-tuned models for the distinct art style.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=kingdom+hearts+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Kingdom Hearts",
        "thumbnail_url": "",
        "tags": ["kingdom-hearts", "kh", "disney", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN (anime model)",
    },
    {
        "id": "kh2_textures",
        "name": "Kingdom Hearts II — HD Texture Pack",
        "description": (
            "HD texture replacements for Kingdom Hearts II (SLUS-21005). "
            "Community-upscaled textures for characters, worlds, and menus."
        ),
        "context": "Multiple authors have published KH2 texture packs on GBAtemp and LoversLab. Check for author's recommended PCSX2 resolution and renderer.",
        "author": "LoversLab Community",
        "author_url": "https://www.loverslab.com",
        "url": "https://www.loverslab.com/search/#q=kingdom+hearts+2+texture&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Kingdom Hearts II",
        "thumbnail_url": "",
        "tags": ["kingdom-hearts", "kh2", "disney", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN (anime model)",
    },
    {
        "id": "sotc_textures",
        "name": "Shadow of the Colossus — HD Textures",
        "description": (
            "Community HD texture replacements for Shadow of the Colossus (SCUS-97472). "
            "Upscaled environment, colossus and Wander textures."
        ),
        "context": "One of the most-requested PS2 texture projects. Look for packs on GBAtemp and Reddit r/ps2 for latest releases.",
        "author": "Reddit r/ps2",
        "author_url": "https://www.reddit.com/r/ps2",
        "url": "https://www.reddit.com/r/ps2/search/?q=shadow+colossus+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Shadow of the Colossus",
        "thumbnail_url": "",
        "tags": ["shadow-of-the-colossus", "sotc", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "gt4_textures",
        "name": "Gran Turismo 4 — HD Car & Track Textures",
        "description": (
            "Community HD texture packs for Gran Turismo 4 (SCUS-97436). "
            "Upscaled car liveries, track environments and UI elements."
        ),
        "context": "GT4 texture packs often ship with per-car files. Check the GBAtemp GT4 thread for author-curated download links and install instructions.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=gran+turismo+4+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Gran Turismo 4",
        "thumbnail_url": "",
        "tags": ["gran-turismo", "gt4", "racing", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "dmc3_textures",
        "name": "Devil May Cry 3 — HD Texture Pack",
        "description": (
            "HD texture replacements for Devil May Cry 3 (SLUS-21048). "
            "Character, environment and menu upscales from the community."
        ),
        "context": "Check LoversLab and GBAtemp for DMC3 texture packs. The game's high-contrast art style responds well to ESRGAN upscaling.",
        "author": "LoversLab Community",
        "author_url": "https://www.loverslab.com",
        "url": "https://www.loverslab.com/search/#q=devil+may+cry+ps2+texture&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Devil May Cry 3",
        "thumbnail_url": "",
        "tags": ["devil-may-cry", "dmc3", "action", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "ratchet_clank_textures",
        "name": "Ratchet & Clank — HD Texture Pack",
        "description": (
            "Community HD textures for Ratchet & Clank (SCUS-97199) and its sequels. "
            "Upscaled character, weapon and planet textures."
        ),
        "context": "Insomniac's colourful art style upscales very well. Check GBAtemp for packs covering R&C, Going Commando and Up Your Arsenal.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=ratchet+clank+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Ratchet & Clank",
        "thumbnail_url": "",
        "tags": ["ratchet-clank", "insomniac", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "xBRZ / ESRGAN",
    },
    {
        "id": "jak_daxter_textures",
        "name": "Jak and Daxter — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Jak and Daxter: The Precursor Legacy (SCUS-97124). "
            "Upscaled environment, character and UI textures."
        ),
        "context": "Jak and Daxter's open world responds beautifully to HD textures. Look on GBAtemp for author posts with recommended settings.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=jak+daxter+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Jak and Daxter",
        "thumbnail_url": "",
        "tags": ["jak-daxter", "naughty-dog", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "xBRZ / ESRGAN",
    },
    {
        "id": "dbz_bt3_textures",
        "name": "Dragon Ball Z: Budokai Tenkaichi 3 — HD Textures",
        "description": (
            "Community HD texture pack for DBZ Budokai Tenkaichi 3 (SLUS-21678). "
            "Upscaled character, arena, and UI textures."
        ),
        "context": "One of the most popular PS2 games for texture modding. Multiple authors have published packs on GBAtemp covering different character rosters.",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=budokai+tenkaichi+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Dragon Ball Z: Budokai Tenkaichi 3",
        "thumbnail_url": "",
        "tags": ["dbz", "dragon-ball", "fighting", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "gta_sa_textures",
        "name": "GTA San Andreas — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Grand Theft Auto: San Andreas (SLUS-20946). "
            "Upscaled world, character and vehicle textures for use in PCSX2."
        ),
        "context": "SA texture packs are very popular. Check GBAtemp and the PCSX2 forums for the latest releases; some packs are split by region (city/countryside).",
        "author": "GBAtemp Community",
        "author_url": "https://gbatemp.net",
        "url": "https://gbatemp.net/search/?q=gta+san+andreas+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "GTA San Andreas",
        "thumbnail_url": "",
        "tags": ["gta", "san-andreas", "open-world", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ico_textures",
        "name": "Ico — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Ico (SCUS-97113). "
            "Upscaled castle, character, and atmospheric environment textures."
        ),
        "context": "Ico's minimalist art style makes it a great candidate for HD textures. Check Reddit r/ps2 and GBAtemp for community packs.",
        "author": "Reddit r/ps2",
        "author_url": "https://www.reddit.com/r/ps2",
        "url": "https://www.reddit.com/r/ps2/search/?q=ico+texture+pack",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Ico",
        "thumbnail_url": "",
        "tags": ["ico", "adventure", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN",
    },
    # ── Game-Specific PNACH Patches ───────────────────────────────────────────
    {
        "id": "gow_widescreen_pnach",
        "name": "God of War I & II — Widescreen Patches",
        "description": (
            "Widescreen (16:9) and 60fps patches for God of War I (SCUS-97399) and "
            "God of War II (SCUS-97402) as PNACH files."
        ),
        "context": "Download the .pnach file and place it in your PCSX2 cheats folder, or import it here using the PNACH panel.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net/pc10.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "God of War",
        "thumbnail_url": "",
        "tags": ["widescreen", "gow", "pnach", "16:9", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "kh_widescreen_pnach",
        "name": "Kingdom Hearts I & II — Widescreen Patches",
        "description": (
            "Widescreen (16:9) PNACH patches for Kingdom Hearts (SLUS-20370) and "
            "Kingdom Hearts II (SLUS-21005)."
        ),
        "context": "PS2Wide hosts the definitive widescreen patches. Import the .pnach into the PNACH panel and deploy to your PCSX2 cheats folder.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net/pc10.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Kingdom Hearts",
        "thumbnail_url": "",
        "tags": ["widescreen", "kingdom-hearts", "pnach", "16:9"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ffx_widescreen_pnach",
        "name": "Final Fantasy X — Widescreen + 60fps Patches",
        "description": (
            "Widescreen and 60fps PNACH patches for Final Fantasy X (SLUS-20312) and "
            "Final Fantasy XII (SLUS-20963)."
        ),
        "context": "Download the specific PNACH for your game region from PS2Wide, then import it into the PNACH panel.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net/pc10.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Final Fantasy X / XII",
        "thumbnail_url": "",
        "tags": ["widescreen", "final-fantasy", "ffx", "pnach", "60fps"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "gt4_widescreen_pnach",
        "name": "Gran Turismo 4 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Gran Turismo 4 (SCUS-97436). "
            "Removes the black bars for a true 16:9 racing experience."
        ),
        "context": "One of the most-requested GT4 patches. Get the .pnach from PS2Wide and import it using the PNACH panel.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net/pc10.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Gran Turismo 4",
        "thumbnail_url": "",
        "tags": ["widescreen", "gran-turismo", "gt4", "racing", "pnach"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "crash_woc_pnach",
        "name": "Crash Bandicoot: Wrath of Cortex — 60fps Patch",
        "description": (
            "60fps and widescreen PNACH patches for Crash Bandicoot: The Wrath of Cortex (SLUS-20238). "
            "Improves the notoriously slow PS2 version."
        ),
        "context": "The 60fps patch significantly improves feel. Grab the .pnach from the PCSX2 widescreen patches GitHub or PS2Wide.",
        "author": "PCSX2 Community",
        "author_url": "https://github.com/PCSX2",
        "url": "https://github.com/PCSX2/PCSX2-Widescreen-Patches",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Crash Bandicoot: Wrath of Cortex",
        "thumbnail_url": "",
        "tags": ["widescreen", "crash-bandicoot", "60fps", "pnach"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "sotc_pnach",
        "name": "Shadow of the Colossus — Widescreen + 60fps",
        "description": (
            "Widescreen and 60fps PNACH patches for Shadow of the Colossus (SCUS-97472). "
            "Makes the game feel dramatically smoother at 16:9."
        ),
        "context": "The 60fps patch is one of the best PCSX2 experiences available. Find the patch file on PS2Wide or the PCSX2 GitHub widescreen patches repository.",
        "author": "PS2Wide Community",
        "author_url": "https://ps2wide.net",
        "url": "https://ps2wide.net/pc10.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Shadow of the Colossus",
        "thumbnail_url": "",
        "tags": ["widescreen", "shadow-of-the-colossus", "sotc", "60fps", "pnach"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Game-Specific Cover Art ───────────────────────────────────────────────
    {
        "id": "cover_art_popular_us",
        "name": "PS2 Cover Art — Popular US Titles (GameTDB)",
        "description": (
            "Download cover art for popular US PS2 titles from GameTDB by entering "
            "the game serial ID (e.g. SLUS-20062). GameTDB provides free, "
            "high-quality cover scans."
        ),
        "context": (
            "Popular serials: Spyro EtD=SLUS-20309, Crash WoC=SLUS-20238, GoW=SCUS-97399, "
            "GT4=SCUS-97436, FFX=SLUS-20312, KH1=SLUS-20370, KH2=SLUS-21005, "
            "SotC=SCUS-97472, GTA SA=SLUS-20946."
        ),
        "author": "GameTDB",
        "author_url": "https://www.gametdb.com",
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "source": "GameTDB",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cover-art", "gametdb", "official", "us"],
        "download_action": "cover_by_id",
        "upscale_tech": "",
    },
    {
        "id": "cover_art_popular_eu",
        "name": "PS2 Cover Art — Popular EU/PAL Titles (GameTDB)",
        "description": (
            "Download PAL region cover art for PS2 games from GameTDB. "
            "Enter the SLES or SCES serial to get the EU cover."
        ),
        "context": (
            "Popular PAL serials: GoW=SCES-53133, GT4=SCES-51719, FFX=SLES-50490, "
            "KH1=SLES-51152, KH2=SLES-54114, SotC=SCES-53326."
        ),
        "author": "GameTDB",
        "author_url": "https://www.gametdb.com",
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "source": "GameTDB",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cover-art", "gametdb", "pal", "eu"],
        "download_action": "cover_by_id",
        "upscale_tech": "",
    },
]

# Collect unique sources for the source filter dropdown
ALL_SOURCES = sorted({e["source"] for e in CATALOGUE})


# ---------------------------------------------------------------------------
# Catalogue card widget
# ---------------------------------------------------------------------------

class CatalogueCard(QFrame):
    """A card in the mod browser showing one catalogue entry."""

    open_url = pyqtSignal(str)
    download_cover = pyqtSignal(dict)
    favorite_toggled = pyqtSignal(str, bool)   # author, is_favorite

    def __init__(self, entry: dict, config: AppConfig, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.config = config
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setMaximumWidth(400)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        type_icons = {
            ModType.TEXTURE_PACK: "🎨",
            ModType.PNACH: "🔧",
            ModType.COVER_ART: "🖼️",
            ModType.SAVE_FILE: "💾",
            ModType.CHEAT: "⚡",
        }
        icon = type_icons.get(self.entry["type"], "📦")

        # Header row: thumbnail + type badge
        header = QHBoxLayout()
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(32, 32)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setText(icon)
        self._thumb_lbl.setStyleSheet("font-size: 22px; background: transparent;")
        header.addWidget(self._thumb_lbl)

        if self.entry.get("thumbnail_url"):
            threading.Thread(
                target=self._load_thumbnail,
                args=(self.entry["thumbnail_url"],),
                daemon=True,
            ).start()

        type_lbl = QLabel(self.entry["type"].value.replace("_", " ").title())
        type_lbl.setStyleSheet(
            "background:#0f3460; color:#80b0ff; border-radius:9px;"
            "padding: 2px 8px; font-size:11px;"
        )
        header.addWidget(type_lbl)

        # Source badge
        src_lbl = QLabel(self.entry.get("source", ""))
        src_lbl.setStyleSheet(
            "background:#1a2050; color:#8080c0; border-radius:9px;"
            "padding: 2px 8px; font-size:10px;"
        )
        header.addWidget(src_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Title
        title = QLabel(self.entry["name"])
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Game badge
        if self.entry.get("game"):
            game_lbl = QLabel(f"🎮 {self.entry['game']}")
            game_lbl.setStyleSheet("color: #80b0ff; font-size: 11px;")
            layout.addWidget(game_lbl)

        # Author row with favorite button
        author_row = QHBoxLayout()
        author_lbl = QLabel(f"by {self.entry['author']}")
        author_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
        author_row.addWidget(author_lbl)
        author_row.addStretch()

        # Favorite author button
        is_fav = self.entry["author"] in getattr(self.config, "favorite_authors", [])
        self._fav_btn = QPushButton("❤" if is_fav else "🤍")
        self._fav_btn.setFixedSize(26, 22)
        self._fav_btn.setStyleSheet(
            "border: none; background: transparent; font-size: 14px;"
            + ("color: #e94560;" if is_fav else "color: #505080;")
        )
        self._fav_btn.setToolTip(
            "Remove from favorites" if is_fav else "Add author to favorites"
        )
        self._fav_btn.clicked.connect(self._toggle_favorite)
        author_row.addWidget(self._fav_btn)

        # Author link button
        if self.entry.get("author_url"):
            author_link = QPushButton("🔗")
            author_link.setFixedSize(26, 22)
            author_link.setStyleSheet("border: none; background: transparent; font-size: 14px; color: #5080d0;")
            author_link.setToolTip(f"Visit author page: {self.entry['author_url']}")
            author_link.clicked.connect(lambda: self.open_url.emit(self.entry["author_url"]))
            author_row.addWidget(author_link)
        layout.addLayout(author_row)

        # Description
        desc = QLabel(self.entry["description"])
        desc.setStyleSheet("color: #9090b0; font-size: 12px;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(60)
        layout.addWidget(desc)

        # Context info (collapsible-style tooltip hint)
        if self.entry.get("context"):
            ctx_lbl = QLabel(f"ℹ {self.entry['context'][:120]}{'…' if len(self.entry['context']) > 120 else ''}")
            ctx_lbl.setStyleSheet(
                "color: #607090; font-size: 10px; font-style: italic;"
                "background: #0a1428; border-radius: 4px; padding: 4px 6px;"
            )
            ctx_lbl.setWordWrap(True)
            ctx_lbl.setToolTip(self.entry["context"])
            layout.addWidget(ctx_lbl)

        # Upscale tech
        if self.entry.get("upscale_tech"):
            tech_lbl = QLabel(f"⚙ {self.entry['upscale_tech']}")
            tech_lbl.setStyleSheet("color: #6080a0; font-size: 10px;")
            layout.addWidget(tech_lbl)

        # Tags
        if self.entry.get("tags"):
            tags_row = QHBoxLayout()
            tags_row.setSpacing(4)
            for tag in self.entry["tags"][:4]:
                tag_lbl = QLabel(tag)
                tag_lbl.setStyleSheet(
                    "background:#1a2050; color:#8080c0; border-radius:6px;"
                    "padding: 2px 6px; font-size:10px;"
                )
                tags_row.addWidget(tag_lbl)
            tags_row.addStretch()
            layout.addLayout(tags_row)

        layout.addStretch()

        visit_btn = QPushButton("🌐 Visit Source")
        visit_btn.setObjectName("primary_btn")
        visit_btn.clicked.connect(lambda: self.open_url.emit(self.entry["url"]))
        layout.addWidget(visit_btn)

        if self.entry.get("download_action") == "cover_by_id":
            dl_btn = QPushButton("🖼 Download Cover by ID")
            dl_btn.clicked.connect(lambda: self.download_cover.emit(self.entry))
            layout.addWidget(dl_btn)

    def _toggle_favorite(self):
        author = self.entry["author"]
        favs = list(getattr(self.config, "favorite_authors", []))
        is_fav = author in favs
        if is_fav:
            favs.remove(author)
        else:
            favs.append(author)
        self.config.favorite_authors = favs
        try:
            save_config(self.config)
        except Exception:
            pass

        new_fav = not is_fav
        self._fav_btn.setText("❤" if new_fav else "🤍")
        self._fav_btn.setStyleSheet(
            "border: none; background: transparent; font-size: 14px;"
            + ("color: #e94560;" if new_fav else "color: #505080;")
        )
        self._fav_btn.setToolTip("Remove from favorites" if new_fav else "Add author to favorites")
        self.favorite_toggled.emit(author, new_fav)

    def _load_thumbnail(self, url: str):
        try:
            import urllib.request
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = f.name
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = resp.read()
            with open(tmp, "wb") as f:
                f.write(data)

            def _update():
                if not self._thumb_lbl:
                    return
                pix = QPixmap(tmp).scaled(
                    28, 28,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if not pix.isNull():
                    self._thumb_lbl.setPixmap(pix)
                    self._thumb_lbl.setStyleSheet("background: #0f1830; border-radius: 4px;")
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

            QTimer.singleShot(0, _update)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Cover art download dialog
# ---------------------------------------------------------------------------

class CoverDownloadDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Download Cover Art")
        self.setMinimumWidth(460)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(QLabel(
            "Enter the PS2 game serial/ID (e.g. SLUS-20062) to download its cover art\n"
            "from GameTDB (https://www.gametdb.com). Cover art is provided free of charge."
        ))

        id_row = QHBoxLayout()
        id_row.addWidget(QLabel("Game ID:"))
        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("e.g. SLUS-20062")
        id_row.addWidget(self._id_edit, 1)
        layout.addLayout(id_row)

        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("Region:"))
        self._region_combo = QComboBox()
        self._region_combo.addItems(["EN", "US", "EU", "JP", "KO", "ZHCN"])
        region_row.addWidget(self._region_combo)
        region_row.addStretch()
        layout.addLayout(region_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        btns = QHBoxLayout()
        self._dl_btn = QPushButton("⬇ Download")
        self._dl_btn.setObjectName("primary_btn")
        self._dl_btn.clicked.connect(self._download)
        btns.addWidget(self._dl_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _download(self):
        from src.core.downloader import fetch_gametdb_art
        game_id = self._id_edit.text().strip()
        if not game_id:
            self._status.setText("⚠  Please enter a Game ID")
            return
        dest_dir = self.config.cover_art_path or str(THUMBNAILS_DIR)
        region = self._region_combo.currentText()
        self._dl_btn.setEnabled(False)
        self._progress.show()
        self._status.setText(f"Downloading cover for {game_id}...")

        def _run():
            path = fetch_gametdb_art(game_id, dest_dir, region)
            if path:
                self._status.setText(f"✅  Saved to: {path}")
            else:
                self._status.setText("❌  Cover not found or download failed.")
            self._dl_btn.setEnabled(True)
            self._progress.hide()

        threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Download-from-URL install dialog
# ---------------------------------------------------------------------------

class DownloadInstallDialog(QDialog):
    """
    Download any direct URL (ZIP, 7z, PNACH, PNG) and import it as a mod.
    Google Drive share links are auto-converted. MEGA links get guidance.
    """

    def __init__(self, config: AppConfig, db, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.setWindowTitle("Download & Install Mod from URL")
        self.setMinimumSize(580, 440)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info = QLabel(
            "<b>Paste a direct download URL below.</b><br>"
            "Supported: HTTPS links to ZIP, 7z, PNACH, PNG.<br>"
            "Google Drive share links are auto-converted. "
            "MEGA links must be downloaded manually."
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://example.com/texture_pack.zip")
        url_row.addWidget(self._url_edit, 1)
        layout.addLayout(url_row)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Mod type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItem("🎨 Texture Pack", ModType.TEXTURE_PACK)
        self._type_combo.addItem("🔧 PNACH Patch", ModType.PNACH)
        self._type_combo.addItem("🖼️ Cover Art", ModType.COVER_ART)
        self._type_combo.addItem("💾 Save File", ModType.SAVE_FILE)
        self._type_combo.addItem("⚡ Cheat", ModType.CHEAT)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        meta_frame = QFrame()
        meta_frame.setObjectName("card")
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(10, 8, 10, 8)
        meta_layout.setSpacing(6)
        meta_layout.addWidget(QLabel("Optional metadata:"))

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Mod name (auto from filename)")
        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("Author name")
        self._game_edit = QLineEdit()
        self._game_edit.setPlaceholderText("Game name or serial ID (e.g. SLUS-20062)")

        for label, edit in [
            ("Name:", self._name_edit),
            ("Author:", self._author_edit),
            ("Game:", self._game_edit),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(60)
            row.addWidget(lbl)
            row.addWidget(edit, 1)
            meta_layout.addLayout(row)
        layout.addWidget(meta_frame)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #9090b0;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        layout.addWidget(self._progress)

        btns = QHBoxLayout()
        self._dl_btn = QPushButton("⬇ Download & Install")
        self._dl_btn.setObjectName("primary_btn")
        self._dl_btn.clicked.connect(self._download)
        btns.addWidget(self._dl_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    @staticmethod
    def _convert_url(url: str) -> str:
        import re
        m = re.search(r"drive\.google\.com/file/d/([^/?]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
        m2 = re.search(r"drive\.google\.com/open[?]id=([^&]+)", url)
        if m2:
            return f"https://drive.google.com/uc?export=download&id={m2.group(1)}"
        return url

    def _download(self):
        raw_url = self._url_edit.text().strip()
        if not raw_url:
            self._status.setText("⚠  Please enter a URL")
            return
        if "mega.nz" in raw_url or "mega.co.nz" in raw_url:
            QMessageBox.information(
                self, "MEGA Link",
                "MEGA links require the MEGA desktop client.\n\n"
                "Please download the file manually, then use\n"
                "the ➕ Import button in the relevant mod panel.",
            )
            return
        url = self._convert_url(raw_url)
        mod_type = self._type_combo.currentData()
        storage = self.config.mods_storage_path
        if not storage:
            QMessageBox.warning(self, "Storage Not Configured",
                "Please configure a Mod Storage folder in Settings first.")
            return
        self._dl_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Downloading...")

        def _run():
            try:
                from urllib.parse import urlparse, unquote
                parsed = urlparse(url)
                fname = Path(unquote(parsed.path)).name or "downloaded_mod"
                if not Path(fname).suffix:
                    fname += ".zip"
                tmpdir = tempfile.mkdtemp(prefix="ps2mm_dl_")
                dest = str(Path(tmpdir) / fname)

                def _progress(recv, total):
                    if total > 0:
                        pct = int(recv / total * 100)
                        QTimer.singleShot(0, lambda: self._progress.setValue(pct))
                    else:
                        QTimer.singleShot(0, lambda: self._progress.setRange(0, 0))

                download_file(url, dest, _progress)
                from src.core.mod_manager import ModManager
                mgr = ModManager(self.db)
                name = self._name_edit.text().strip() or Path(fname).stem
                author = self._author_edit.text().strip()
                game = self._game_edit.text().strip()
                mod = mgr.install_from_folder(
                    source_path=dest, mod_type=mod_type, dest_base=storage,
                    name=name, author=author, game_id=game,
                )
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

                def _done():
                    self._progress.setRange(0, 100)
                    self._progress.setValue(100)
                    self._status.setText(f"✅  Installed: {mod.name}")
                    self._dl_btn.setEnabled(True)
                QTimer.singleShot(0, _done)
            except DownloadError as exc:
                def _err():
                    self._status.setText(f"❌  Download failed: {exc}")
                    self._progress.hide()
                    self._dl_btn.setEnabled(True)
                QTimer.singleShot(0, _err)
            except Exception as exc:
                def _err2():
                    self._status.setText(f"❌  Error: {exc}")
                    self._progress.hide()
                    self._dl_btn.setEnabled(True)
                QTimer.singleShot(0, _err2)

        threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# PNACH GitHub browser dialog
# ---------------------------------------------------------------------------

class PnachGitHubDialog(QDialog):
    """
    Browse and download official PCSX2 widescreen PNACH patches directly
    from the PCSX2 GitHub repository.

    Allows users to:
    - Load the full index of available patches from GitHub
    - Search by 8-digit game CRC
    - Download and install patches into the configured PNACH folder
    """

    def __init__(self, config: AppConfig, db, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.setWindowTitle("🔧 Fetch PNACH from PCSX2 GitHub")
        self.setMinimumSize(620, 500)
        self._patches: List[dict] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        info = QLabel(
            "<b>Download official widescreen PNACH patches from the PCSX2 GitHub repository.</b><br>"
            "These patches enable 16:9 widescreen mode for hundreds of PS2 games.<br>"
            "All patches are from the open-source PCSX2 project (MIT licence)."
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        # CRC search row
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Game CRC (8 hex digits):"))
        self._crc_edit = QLineEdit()
        self._crc_edit.setPlaceholderText("e.g. F0A235B4")
        self._crc_edit.setMaxLength(8)
        self._crc_edit.textChanged.connect(self._filter_list)
        search_row.addWidget(self._crc_edit, 1)

        self._check_btn = QPushButton("🔍 Check CRC")
        self._check_btn.clicked.connect(self._check_single_crc)
        search_row.addWidget(self._check_btn)
        layout.addLayout(search_row)

        # Index browser
        index_row = QHBoxLayout()
        self._load_btn = QPushButton("📋 Load Full Patch Index")
        self._load_btn.setObjectName("primary_btn")
        self._load_btn.setToolTip("Fetch the complete list of widescreen patches from PCSX2 GitHub (requires internet)")
        self._load_btn.clicked.connect(self._load_index)
        index_row.addWidget(self._load_btn)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
        index_row.addWidget(self._count_lbl)
        index_row.addStretch()
        layout.addLayout(index_row)

        # Patch list
        self._list_widget = QScrollArea()
        self._list_widget.setWidgetResizable(True)
        self._list_widget.setFrameShape(QFrame.Shape.StyledPanel)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        self._list_widget.setWidget(self._list_container)
        layout.addWidget(self._list_widget, 1)

        # Progress / status
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #9090b0; font-size: 12px;")
        layout.addWidget(self._status)

        btns = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _load_index(self):
        self._load_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Fetching patch index from PCSX2 GitHub…")

        def _run():
            patches = list_pcsx2_widescreen_patches(timeout=15)

            def _done():
                self._patches = patches
                self._progress.hide()
                self._load_btn.setEnabled(True)
                if patches:
                    self._count_lbl.setText(f"  {len(patches)} patches available")
                    self._status.setText(f"✅  Loaded {len(patches)} widescreen patches from PCSX2 GitHub.")
                    self._populate_list(patches)
                else:
                    self._status.setText("❌  Could not fetch patch index. Check your internet connection.")

            QTimer.singleShot(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _check_single_crc(self):
        crc = self._crc_edit.text().strip().upper()
        if len(crc) != 8:
            self._status.setText("⚠  Please enter a valid 8-digit hex CRC (e.g. F0A235B4)")
            return
        self._check_btn.setEnabled(False)
        self._progress.show()
        self._status.setText(f"Checking for widescreen patch for CRC {crc}…")

        def _run():
            result = search_pcsx2_patches_by_crc(crc, timeout=10)

            def _done():
                self._progress.hide()
                self._check_btn.setEnabled(True)
                if result:
                    self._patches = [result]
                    self._populate_list([result])
                    self._status.setText(f"✅  Widescreen patch found for {crc}!")
                else:
                    self._populate_list([])
                    self._status.setText(f"❌  No widescreen patch found for CRC {crc}.")

            QTimer.singleShot(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _filter_list(self, text: str):
        if not self._patches:
            return
        q = text.strip().upper()
        filtered = [p for p in self._patches if q in p["crc"]] if q else self._patches
        self._populate_list(filtered)

    def _populate_list(self, patches: List[dict]):
        # Remove all existing widgets except the trailing stretch
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for patch in patches[:200]:  # cap display at 200 for UI performance (PCSX2 repo has ~500+ patches)
            row = self._make_patch_row(patch)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

        if not patches:
            lbl = QLabel("No patches match the current filter.")
            lbl.setStyleSheet("color: #606080; font-size: 12px; padding: 8px;")
            self._list_layout.insertWidget(0, lbl)

    def _make_patch_row(self, patch: dict) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setMaximumHeight(44)
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        crc_lbl = QLabel(f"<b>{patch['crc']}</b>")
        crc_lbl.setStyleSheet("font-family: monospace; font-size: 12px; color: #80b0ff;")
        crc_lbl.setFixedWidth(110)
        row.addWidget(crc_lbl)

        file_lbl = QLabel(patch["filename"])
        file_lbl.setStyleSheet("color: #9090b0; font-size: 11px;")
        row.addWidget(file_lbl, 1)

        dl_btn = QPushButton("⬇ Install")
        dl_btn.setFixedWidth(80)
        dl_btn.setObjectName("primary_btn")
        dl_btn.clicked.connect(lambda _checked, p=patch: self._install_patch(p, dl_btn))
        row.addWidget(dl_btn)

        return frame

    def _install_patch(self, patch: dict, btn: QPushButton):
        pnach_dir = self.config.pnach_path
        if not pnach_dir:
            QMessageBox.warning(
                self, "PNACH Folder Not Configured",
                "Please configure a PNACH folder in Settings before installing patches.",
            )
            return
        btn.setEnabled(False)
        btn.setText("⏳")
        self._status.setText(f"Downloading {patch['filename']}…")

        def _run():
            path = download_pcsx2_widescreen_patch(patch["crc"], pnach_dir, timeout=15)

            def _done():
                btn.setEnabled(True)
                if path:
                    btn.setText("✅")
                    btn.setStyleSheet("color: #40c040;")
                    self._status.setText(f"✅  Installed: {path}")
                    # Register the patch in the mod database
                    if self.db is not None:
                        try:
                            from src.core.mod_manager import ModManager
                            mgr = ModManager(self.db)
                            mgr.install_from_folder(
                                source_path=path,
                                mod_type=ModType.PNACH,
                                dest_base=pnach_dir,
                                name=f"Widescreen Patch ({patch['crc']})",
                                author="PCSX2 Team",
                            )
                        except Exception as _reg_exc:  # DB registration is best-effort
                            import sys
                            print(f"[PS2MM] PNACH DB registration warning: {_reg_exc}", file=sys.stderr)
                else:
                    btn.setText("⬇ Install")
                    self._status.setText(f"❌  Download failed for {patch['filename']}.")

            QTimer.singleShot(0, _done)

        threading.Thread(target=_run, daemon=True).start()



    def __init__(self, entries: list, config: AppConfig, parent=None):
        super().__init__(parent)
        self._all_entries = entries
        self.config = config
        self._current_query = ""
        self._current_source = ""
        self._current_author = ""
        self._show_favs_only = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_container = QWidget()
        self._cards_layout = QGridLayout(self._cards_container)
        self._cards_layout.setContentsMargins(4, 8, 4, 8)
        self._cards_layout.setSpacing(14)
        self._scroll.setWidget(self._cards_container)
        layout.addWidget(self._scroll, 1)
        self._populate(entries)

    def apply_filters(self, query: str = "", source: str = "",
                      author: str = "", favs_only: bool = False):
        self._current_query = query
        self._current_source = source
        self._current_author = author
        self._show_favs_only = favs_only

        q = query.lower()
        fav_authors = getattr(self.config, "favorite_authors", [])

        filtered = []
        for e in self._all_entries:
            if q and not (
                q in e.get("name", "").lower()
                or q in e.get("description", "").lower()
                or q in e.get("author", "").lower()
                or q in e.get("game", "").lower()
                or q in e.get("context", "").lower()
                or any(q in t.lower() for t in e.get("tags", []))
            ):
                continue
            if source and e.get("source", "") != source:
                continue
            if author and e.get("author", "") != author:
                continue
            if favs_only and e.get("author", "") not in fav_authors:
                continue
            filtered.append(e)

        self._populate(filtered)

    def _populate(self, entries: list):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = 3
        for i, entry in enumerate(entries):
            card = CatalogueCard(entry, self.config)
            card.open_url.connect(self._open_url)
            card.download_cover.connect(self._download_cover)
            card.favorite_toggled.connect(self.favorite_toggled)
            self._cards_layout.addWidget(card, i // cols, i % cols)

        remainder = len(entries) % cols
        if remainder and entries:
            for j in range(cols - remainder):
                spacer = QWidget()
                spacer.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                self._cards_layout.addWidget(spacer, len(entries) // cols, remainder + j)

    def _open_url(self, url: str):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _download_cover(self, _entry: dict):
        dlg = CoverDownloadDialog(self.config, self)
        dlg.exec()


# ---------------------------------------------------------------------------
# Browse panel
# ---------------------------------------------------------------------------

class BrowsePanel(BasePanel):
    """Panel for discovering and downloading mods from public sources."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(
            "🌐  Browse & Download",
            "Discover community mods and resources",
            parent=parent,
        )
        self.config = config
        self._db = None
        self._build()

    def set_db(self, db):
        self._db = db

    def _build(self):
        content = self._content_layout

        # ── Search + download toolbar ────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search by name, game, author, tag…")
        self._search.setObjectName("search_bar")
        self._search.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self._search, 1)

        dl_btn = QPushButton("⬇ Download from URL")
        dl_btn.setObjectName("primary_btn")
        dl_btn.setToolTip(
            "Paste a direct download link (ZIP, 7z, PNACH, Google Drive…) "
            "to download and install a mod"
        )
        dl_btn.clicked.connect(self._open_download_dialog)
        toolbar.addWidget(dl_btn)

        pnach_btn = QPushButton("🔧 Fetch PNACH from GitHub")
        pnach_btn.setToolTip(
            "Browse and download official PCSX2 widescreen PNACH patches "
            "directly from the PCSX2 GitHub repository"
        )
        pnach_btn.clicked.connect(self._open_pnach_github_dialog)
        toolbar.addWidget(pnach_btn)

        reload_btn = QPushButton("🔄 Reload")
        reload_btn.setToolTip("Clear all filters and reload the catalogue")
        reload_btn.clicked.connect(self._reload_catalogue)
        toolbar.addWidget(reload_btn)

        content.addLayout(toolbar)

        # ── Filter row ───────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        # Source filter
        filter_row.addWidget(QLabel("🌐 Source:"))
        self._source_filter = QComboBox()
        self._source_filter.setMinimumWidth(130)
        self._source_filter.addItem("All Sources", "")
        for src in ALL_SOURCES:
            self._source_filter.addItem(src, src)
        self._source_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._source_filter)

        # Author filter
        filter_row.addWidget(QLabel("👤 Author:"))
        self._author_filter = QComboBox()
        self._author_filter.setMinimumWidth(150)
        self._author_filter.addItem("All Authors", "")
        authors = sorted({e["author"] for e in CATALOGUE if e.get("author")})
        for a in authors:
            fav = a in getattr(self.config, "favorite_authors", [])
            self._author_filter.addItem(("❤ " if fav else "") + a, a)
        self._author_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._author_filter)

        # Favorites only checkbox
        self._favs_check = QCheckBox("❤ Favorites Only")
        self._favs_check.setStyleSheet("color: #c08090; font-size: 12px;")
        self._favs_check.stateChanged.connect(self._apply_filters)
        filter_row.addWidget(self._favs_check)

        filter_row.addStretch()
        content.addLayout(filter_row)

        note = QLabel(
            "ℹ  Community-maintained public resources. "
            "PS2 Mod Manager does not host or distribute any copyrighted content."
        )
        note.setStyleSheet(
            "background: #0f1830; color: #7070a0; font-size: 12px;"
            "border-radius: 6px; padding: 8px 12px;"
        )
        note.setWordWrap(True)
        content.addWidget(note)

        # ── Patreon support banner ────────────────────────────────────────
        from PyQt6.QtWidgets import QFrame as _QFrame
        patreon_frame = _QFrame()
        patreon_frame.setObjectName("card")
        patreon_frame.setStyleSheet(
            "QFrame#card { border: 1px solid #f96854; background: #1e1010; "
            "border-radius: 8px; padding: 0px; }"
        )
        patreon_row = QHBoxLayout(patreon_frame)
        patreon_row.setContentsMargins(14, 10, 14, 10)
        patreon_row.setSpacing(12)
        heart_lbl = QLabel("❤")
        heart_lbl.setStyleSheet("font-size: 24px;")
        patreon_row.addWidget(heart_lbl)
        p_msg = QLabel(
            "<b style='color:#f96854;'>Enjoying PS2 Mod Manager?</b>  "
            "Support the developer on "
            "<a href='https://www.patreon.com/c/DeadOnTheInside' "
            "style='color:#f96854;'>Patreon</a> "
            "to keep the project alive!"
        )
        p_msg.setOpenExternalLinks(True)
        p_msg.setWordWrap(False)
        p_msg.setStyleSheet("color: #c0a0a0; font-size: 12px;")
        patreon_row.addWidget(p_msg, 1)
        p_btn = QPushButton("❤  Patreon")
        p_btn.setObjectName("patreon_btn")
        p_btn.setFixedWidth(110)
        p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        p_btn.clicked.connect(
            lambda: self._open_url("https://www.patreon.com/c/DeadOnTheInside")
        )
        patreon_row.addWidget(p_btn)
        content.addWidget(patreon_frame)

        # ── Tabs ─────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        tab_defs = [
            ("All", None),
            ("🎨 Textures", ModType.TEXTURE_PACK),
            ("🔧 PNACH", ModType.PNACH),
            ("🖼️ Covers", ModType.COVER_ART),
            ("💾 Saves", ModType.SAVE_FILE),
            ("⚡ Cheats", ModType.CHEAT),
        ]

        self._tab_contents: List[_CatalogueTabContent] = []
        for label, mod_type in tab_defs:
            entries = (
                CATALOGUE if mod_type is None
                else [e for e in CATALOGUE if e["type"] == mod_type]
            )
            tab = _CatalogueTabContent(entries, self.config)
            tab.favorite_toggled.connect(self._on_favorite_toggled)
            self._tab_contents.append(tab)
            self._tabs.addTab(tab, label)

        content.addWidget(self._tabs, 1)

    def _apply_filters(self):
        query = self._search.text()
        source = self._source_filter.currentData() or ""
        author = self._author_filter.currentData() or ""
        favs_only = self._favs_check.isChecked()
        for tab in self._tab_contents:
            tab.apply_filters(query, source, author, favs_only)

    def _on_favorite_toggled(self, author: str, is_fav: bool):
        """Rebuild author dropdown when favorites change."""
        self._author_filter.blockSignals(True)
        current = self._author_filter.currentData() or ""
        self._author_filter.clear()
        self._author_filter.addItem("All Authors", "")
        authors = sorted({e["author"] for e in CATALOGUE if e.get("author")})
        for a in authors:
            fav = a in getattr(self.config, "favorite_authors", [])
            self._author_filter.addItem(("❤ " if fav else "") + a, a)
        idx = self._author_filter.findData(current)
        if idx >= 0:
            self._author_filter.setCurrentIndex(idx)
        self._author_filter.blockSignals(False)

    def _open_download_dialog(self):
        dlg = DownloadInstallDialog(self.config, self._db, self)
        dlg.exec()

    def _open_pnach_github_dialog(self):
        dlg = PnachGitHubDialog(self.config, self._db, self)
        dlg.exec()

    def _open_url(self, url: str):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _reload_catalogue(self):
        """Clear all filters and reset the catalogue view."""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._source_filter.setCurrentIndex(0)
        self._author_filter.setCurrentIndex(0)
        self._favs_check.setChecked(False)
        self._apply_filters()
        self.emit_status("Catalogue reloaded")

    def refresh(self):
        self._apply_filters()
