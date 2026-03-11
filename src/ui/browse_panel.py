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
        "author": "",
        "author_url": "https://wiki.pcsx2.net/Special:RecentChanges",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/tags/ps2-texture-pack/",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=ps2+texture&t=files",
        "is_hub": True,
        "nsfw": True,
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
        "author": "",
        "author_url": "https://www.nexusmods.com/pcsx2",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.ps2-home.com/forum/viewforum.php?f=50",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=texture+pack&sort=new",
        "is_hub": True,
        "nsfw": False,
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
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
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
        "author": "PCSX2 Team",
        "author_url": "https://github.com/PCSX2",
        "is_hub": False,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/Forum-Patches-and-Cheats",
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=pnach&t=file_update",
        "is_hub": True,
        "nsfw": False,
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
        "is_hub": False,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gamesdb.launchbox-app.com/platforms/games/11",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://archive.org/search?query=PS2+cover+art&mediatype=image",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gamefaqs.gamespot.com/ps2/category/929-saves",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://ps2saves.com",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://github.com/PCSX2/cheatdb/graphs/contributors",
        "is_hub": True,
        "nsfw": False,
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
        "author_url": "https://www.codejunkies.com/ps2/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-cheats.19/",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.patreon.com/search?q=ps2+texture+pcsx2",
        "is_hub": True,
        "nsfw": False,
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
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "support", "dev"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "eragon_hd_textures",
        "name": "Eragon — HD Texture Pack (Free on Patreon)",
        "description": (
            "HD texture replacement pack for Eragon (SLUS-21228 / SLES-54053). "
            "Free attachment on the DeadOnTheInside Patreon post. "
            "Contains upscaled environment, character and dragon textures. "
            "Folder inside the download is named 'replacement' — the app handles "
            "this automatically when you enter the Game ID (SLUS-21228)."
        ),
        "context": (
            "Download steps: 1) Log in to Patreon and open the post. "
            "2) Click the attachment to download the ZIP. "
            "3) In PS2 Mod Manager go to Texture Packs → ➕ Import. "
            "4) Select the ZIP and enter Game ID 'SLUS-21228'. "
            "The app will automatically place files into "
            "textures/SLUS-21228/replacements/ so PCSX2 can find them."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/eragon-hd-ps2-146041522",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Eragon",
        "thumbnail_url": "",
        "tags": ["eragon", "hd", "esrgan", "ps2", "free", "patreon"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    # ── Post 147372741: HD Textures + PNACH + Lights (multi-part zips) ────────
    {
        "id": "patreon_147372741_hd_textures",
        "name": "DeadOnTheInside — PS2 HD Texture Pack (Large, Multi-Part)",
        "description": (
            "Large HD texture replacement pack split across multiple ZIP parts. "
            "Free on Patreon — a free account is required to download attachments. "
            "Download ALL parts to the same folder, then use ➕ Import → 📦 Archive "
            "and select Part 1; PS2 Mod Manager will automatically find and extract "
            "all remaining parts."
        ),
        "context": (
            "Multi-part import steps: 1) Log in to Patreon (free account). "
            "2) Download every numbered ZIP part from the post to the SAME folder. "
            "3) In Texture Packs → ➕ Import → 📦 Archive, select the first part. "
            "4) Enter the Game ID shown in the post. "
            "The app extracts all parts together and places textures in "
            "textures/<SERIAL>/replacements/ automatically."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/147372741",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "hd", "esrgan", "ps2", "free", "multi-part", "large"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "patreon_147372741_pnach",
        "name": "DeadOnTheInside — PNACH Patch (Post 147372741)",
        "description": (
            "PNACH patch included with the large HD texture pack post on Patreon. "
            "May include widescreen, 60 fps, or other game improvements. "
            "Free on Patreon — a free account is required. "
            "Download the PNACH file and place it in your PCSX2 cheats folder, "
            "or import via PS2 Mod Manager's PNACH Patches panel."
        ),
        "context": (
            "Download from the Patreon post, then import via PNACH Patches → ➕ Import → 📄 File. "
            "The CRC in the filename must match your game disc. "
            "Check the post description for the correct game serial / CRC."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/147372741",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "pnach", "widescreen", "free", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "patreon_147372741_lights",
        "name": "DeadOnTheInside — Upscaled Lights & Effects Texture Pack",
        "description": (
            "Upscaled lights and effects texture replacement pack included in the "
            "same Patreon post as the main HD textures. "
            "Replaces bloom, glow, particle, and lighting textures for an enhanced look. "
            "Free on Patreon — a free account is required. "
            "Import separately from the main HD pack using the same Game ID."
        ),
        "context": (
            "Download from the Patreon post, then import via Texture Packs → ➕ Import. "
            "This is a separate pack from the main HD textures — import both for the "
            "full visual upgrade. Enter the Game ID shown in the post."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/147372741",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "hd", "lights", "effects", "esrgan", "ps2", "free"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    # ── DeadOnTheInside — Game-Specific Texture Packs ────────────────────────
    # Each entry links to the creator's Patreon page; open it and search for the
    # game name to find the exact post containing that pack.
    {
        "id": "doti_gow1_textures",
        "name": "DeadOnTheInside — God of War HD Texture Pack",
        "description": (
            "HD texture replacement pack for God of War (SCUS-97399 / SCES-53133). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and UI textures using ESRGAN. "
            "Free Patreon membership required to download."
        ),
        "context": (
            "Find the post on the creator's page by searching for 'God of War'. "
            "Download the attachment, then import via Texture Packs → ➕ Import "
            "with Game ID SCUS-97399 (US) or SCES-53133 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "God of War",
        "thumbnail_url": "",
        "tags": ["god of war", "gow", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_gow2_textures",
        "name": "DeadOnTheInside — God of War II HD Texture Pack",
        "description": (
            "HD texture replacement pack for God of War II (SCUS-97481 / SCES-54206). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and boss textures using ESRGAN. "
            "Free Patreon membership required."
        ),
        "context": (
            "Find the post on the creator's page by searching for 'God of War II'. "
            "Import with Game ID SCUS-97481 (US) or SCES-54206 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "God of War II",
        "thumbnail_url": "",
        "tags": ["god of war 2", "gow2", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_kh1_textures",
        "name": "DeadOnTheInside — Kingdom Hearts HD Texture Pack",
        "description": (
            "HD texture replacement pack for Kingdom Hearts (SLUS-20370 / SLES-51150). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Kingdom Hearts' on the creator's Patreon page. "
            "Import with Game ID SLUS-20370 (US) or SLES-51150 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Kingdom Hearts",
        "thumbnail_url": "",
        "tags": ["kingdom hearts", "kh1", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_kh2_textures",
        "name": "DeadOnTheInside — Kingdom Hearts II HD Texture Pack",
        "description": (
            "HD texture replacement pack for Kingdom Hearts II (SLUS-21005 / SLES-54114). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Kingdom Hearts II' on the creator's Patreon page. "
            "Import with Game ID SLUS-21005 (US) or SLES-54114 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Kingdom Hearts II",
        "thumbnail_url": "",
        "tags": ["kingdom hearts 2", "kh2", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_ffx_textures",
        "name": "DeadOnTheInside — Final Fantasy X HD Texture Pack",
        "description": (
            "HD texture replacement pack for Final Fantasy X (SLUS-20312 / SLES-50490). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and battle textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Final Fantasy X' on the creator's Patreon page. "
            "Import with Game ID SLUS-20312 (US) or SLES-50490 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Final Fantasy X",
        "thumbnail_url": "",
        "tags": ["final fantasy x", "ffx", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_ff12_textures",
        "name": "DeadOnTheInside — Final Fantasy XII HD Texture Pack",
        "description": (
            "HD texture replacement pack for Final Fantasy XII (SLUS-21475 / SLES-54354). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and monster textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Final Fantasy XII' on the creator's Patreon page. "
            "Import with Game ID SLUS-21475 (US) or SLES-54354 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Final Fantasy XII",
        "thumbnail_url": "",
        "tags": ["final fantasy xii", "ff12", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_sotc_textures",
        "name": "DeadOnTheInside — Shadow of the Colossus HD Texture Pack",
        "description": (
            "HD texture replacement pack for Shadow of the Colossus (SCUS-97472 / SCES-53326). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled landscape, colossus, and sky textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Shadow of the Colossus' on the creator's Patreon page. "
            "Import with Game ID SCUS-97472 (US) or SCES-53326 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Shadow of the Colossus",
        "thumbnail_url": "",
        "tags": ["shadow of the colossus", "sotc", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_ico_textures",
        "name": "DeadOnTheInside — Ico HD Texture Pack",
        "description": (
            "HD texture replacement pack for Ico (SCUS-97113 / SCES-50760). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled castle, environment, and character textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Ico' on the creator's Patreon page. "
            "Import with Game ID SCUS-97113 (US) or SCES-50760 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Ico",
        "thumbnail_url": "",
        "tags": ["ico", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_sh2_textures",
        "name": "DeadOnTheInside — Silent Hill 2 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Silent Hill 2 (SLUS-20228 / SLES-50356). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled fog, environment, monster, and character textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Silent Hill 2' on the creator's Patreon page. "
            "Import with Game ID SLUS-20228 (US) or SLES-50356 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Silent Hill 2",
        "thumbnail_url": "",
        "tags": ["silent hill 2", "sh2", "hd", "esrgan", "horror", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_sh3_textures",
        "name": "DeadOnTheInside — Silent Hill 3 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Silent Hill 3 (SLUS-20622 / SLES-51434). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, monster, and character textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Silent Hill 3' on the creator's Patreon page. "
            "Import with Game ID SLUS-20622 (US) or SLES-51434 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Silent Hill 3",
        "thumbnail_url": "",
        "tags": ["silent hill 3", "sh3", "hd", "esrgan", "horror", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_dmc3_textures",
        "name": "DeadOnTheInside — Devil May Cry 3 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Devil May Cry 3: Dante's Awakening "
            "(SLUS-21087 / SLES-53541). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and demon textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Devil May Cry 3' on the creator's Patreon page. "
            "Import with Game ID SLUS-21087 (US) or SLES-53541 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Devil May Cry 3",
        "thumbnail_url": "",
        "tags": ["devil may cry 3", "dmc3", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_re4_textures",
        "name": "DeadOnTheInside — Resident Evil 4 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Resident Evil 4 (SLUS-21134 / SLES-53702). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and enemy textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Resident Evil 4' on the creator's Patreon page. "
            "Import with Game ID SLUS-21134 (US) or SLES-53702 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Resident Evil 4",
        "thumbnail_url": "",
        "tags": ["resident evil 4", "re4", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_mgs2_textures",
        "name": "DeadOnTheInside — Metal Gear Solid 2 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Metal Gear Solid 2: Sons of Liberty "
            "(SLUS-20144 / SLES-50788). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and HUD textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Metal Gear Solid 2' on the creator's Patreon page. "
            "Import with Game ID SLUS-20144 (US) or SLES-50788 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Metal Gear Solid 2: Sons of Liberty",
        "thumbnail_url": "",
        "tags": ["metal gear solid 2", "mgs2", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_mgs3_textures",
        "name": "DeadOnTheInside — Metal Gear Solid 3 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Metal Gear Solid 3: Snake Eater "
            "(SLUS-20718 / SLES-52456). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled jungle, character, and environment textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Metal Gear Solid 3' on the creator's Patreon page. "
            "Import with Game ID SLUS-20718 (US) or SLES-52456 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Metal Gear Solid 3: Snake Eater",
        "thumbnail_url": "",
        "tags": ["metal gear solid 3", "mgs3", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_persona3_textures",
        "name": "DeadOnTheInside — Persona 3 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Persona 3 / Persona 3 FES "
            "(SLUS-21621 / SLUS-21751 / SLES-54532). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled dungeon, character, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Persona 3' on the creator's Patreon page. "
            "Import with Game ID SLUS-21621 (P3 US), SLUS-21751 (P3 FES US), or SLES-54532 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Persona 3",
        "thumbnail_url": "",
        "tags": ["persona 3", "p3", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_persona4_textures",
        "name": "DeadOnTheInside — Persona 4 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Persona 4 (SLUS-21782 US / SLES-55474 EU). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled dungeon, character, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Persona 4' on the creator's Patreon page. "
            "Import with Game ID SLUS-21782 (US) or SLES-55474 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Persona 4",
        "thumbnail_url": "",
        "tags": ["persona 4", "p4", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_okami_textures",
        "name": "DeadOnTheInside — Okami HD Texture Pack",
        "description": (
            "HD texture replacement pack for Okami (SLUS-21115 / SLES-54439). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and brushstroke textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Okami' on the creator's Patreon page. "
            "Import with Game ID SLUS-21115 (US) or SLES-54439 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Okami",
        "thumbnail_url": "",
        "tags": ["okami", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_gtasa_textures",
        "name": "DeadOnTheInside — GTA San Andreas HD Texture Pack",
        "description": (
            "HD texture replacement pack for Grand Theft Auto: San Andreas "
            "(SLUS-20946 / SLES-52541). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled building, road, vegetation, and character textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'San Andreas' on the creator's Patreon page. "
            "Import with Game ID SLUS-20946 (US) or SLES-52541 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Grand Theft Auto: San Andreas",
        "thumbnail_url": "",
        "tags": ["gta san andreas", "gta sa", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_dbz_bt3_textures",
        "name": "DeadOnTheInside — Dragon Ball Z BT3 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Dragon Ball Z: Budokai Tenkaichi 3 "
            "(SLUS-21678 / SLES-55236). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, stage, and effect textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Budokai Tenkaichi' on the creator's Patreon page. "
            "Import with Game ID SLUS-21678 (US) or SLES-55236 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Dragon Ball Z: Budokai Tenkaichi 3",
        "thumbnail_url": "",
        "tags": ["dragon ball z", "dbz", "budokai tenkaichi 3", "bt3", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_tekken5_textures",
        "name": "DeadOnTheInside — Tekken 5 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Tekken 5 (SLUS-21059 / SLES-53971). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled fighter, stage, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Tekken 5' on the creator's Patreon page. "
            "Import with Game ID SLUS-21059 (US) or SLES-53971 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Tekken 5",
        "thumbnail_url": "",
        "tags": ["tekken 5", "hd", "esrgan", "fighting", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_dqviii_textures",
        "name": "DeadOnTheInside — Dragon Quest VIII HD Texture Pack",
        "description": (
            "HD texture replacement pack for Dragon Quest VIII: Journey of the Cursed King "
            "(SLUS-21207 / SLES-53974). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and monster textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Dragon Quest VIII' on the creator's Patreon page. "
            "Import with Game ID SLUS-21207 (US) or SLES-53974 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Dragon Quest VIII",
        "thumbnail_url": "",
        "tags": ["dragon quest viii", "dqviii", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_jak_textures",
        "name": "DeadOnTheInside — Jak and Daxter HD Texture Pack",
        "description": (
            "HD texture replacement pack for Jak and Daxter: The Precursor Legacy "
            "(SCUS-97124 / SCES-50361). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and effect textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Jak and Daxter' on the creator's Patreon page. "
            "Import with Game ID SCUS-97124 (US) or SCES-50361 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Jak and Daxter: The Precursor Legacy",
        "thumbnail_url": "",
        "tags": ["jak and daxter", "jak", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_ratchet_clank_textures",
        "name": "DeadOnTheInside — Ratchet & Clank HD Texture Pack",
        "description": (
            "HD texture replacement pack for Ratchet & Clank (SCUS-97198 / SCES-50916). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled planet, character, and weapon textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Ratchet Clank' on the creator's Patreon page. "
            "Import with Game ID SCUS-97198 (US) or SCES-50916 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Ratchet & Clank",
        "thumbnail_url": "",
        "tags": ["ratchet clank", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_sly_cooper_textures",
        "name": "DeadOnTheInside — Sly Cooper HD Texture Pack",
        "description": (
            "HD texture replacement pack for Sly Cooper and the Thievius Raccoonus "
            "(SCUS-97199 US / SCES-51040 EU). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and HUD textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Sly Cooper' on the creator's Patreon page. "
            "Import with Game ID SCUS-97199 (US) or SCES-51040 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Sly Cooper and the Thievius Raccoonus",
        "thumbnail_url": "",
        "tags": ["sly cooper", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_crash_woc_textures",
        "name": "DeadOnTheInside — Crash Bandicoot: WoC HD Texture Pack",
        "description": (
            "HD texture replacement pack for Crash Bandicoot: Wrath of Cortex "
            "(SLUS-20466 / SLES-50448). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, level, and environment textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Crash Bandicoot Wrath' on the creator's Patreon page. "
            "Import with Game ID SLUS-20466 (US) or SLES-50448 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Crash Bandicoot: The Wrath of Cortex",
        "thumbnail_url": "",
        "tags": ["crash bandicoot", "wrath of cortex", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_spyro_textures",
        "name": "DeadOnTheInside — Spyro: Enter the Dragonfly HD Texture Pack",
        "description": (
            "HD texture replacement pack for Spyro: Enter the Dragonfly "
            "(SLUS-20309 / SLES-50816). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, world, and effect textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Spyro' on the creator's Patreon page. "
            "Import with Game ID SLUS-20309 (US) or SLES-50816 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Spyro: Enter the Dragonfly",
        "thumbnail_url": "",
        "tags": ["spyro", "enter the dragonfly", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_dark_cloud_textures",
        "name": "DeadOnTheInside — Dark Cloud HD Texture Pack",
        "description": (
            "HD texture replacement pack for Dark Cloud (SCUS-97111 US / SCES-50295 EU). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled dungeon, character, and world-building textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Dark Cloud' on the creator's Patreon page. "
            "Import with the Game ID shown on your disc label or in PCSX2's game list "
            "(SCUS-97111 US, SCES-50295 EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Dark Cloud",
        "thumbnail_url": "",
        "tags": ["dark cloud", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_star_ocean3_textures",
        "name": "DeadOnTheInside — Star Ocean: Till the End of Time HD Texture Pack",
        "description": (
            "HD texture replacement pack for Star Ocean: Till the End of Time "
            "(SLUS-20733 / SLES-51752). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled world, character, and battle textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Star Ocean' on the creator's Patreon page. "
            "Import with Game ID SLUS-20733 (US) or SLES-51752 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Star Ocean: Till the End of Time",
        "thumbnail_url": "",
        "tags": ["star ocean 3", "star ocean", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_gt4_textures",
        "name": "DeadOnTheInside — Gran Turismo 4 HD Texture Pack",
        "description": (
            "HD texture replacement pack for Gran Turismo 4 (SCUS-97328 / SCES-51719). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled track, car, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Gran Turismo 4' on the creator's Patreon page. "
            "Import with Game ID SCUS-97328 (US) or SCES-51719 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Gran Turismo 4",
        "thumbnail_url": "",
        "tags": ["gran turismo 4", "gt4", "hd", "esrgan", "racing", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_burnout3_textures",
        "name": "DeadOnTheInside — Burnout 3: Takedown HD Texture Pack",
        "description": (
            "HD texture replacement pack for Burnout 3: Takedown (SLUS-20872 / SLES-52456). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled vehicle, road, and environment textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Burnout 3' on the creator's Patreon page. "
            "Import with Game ID SLUS-20872 (US) or SLES-52456 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Burnout 3: Takedown",
        "thumbnail_url": "",
        "tags": ["burnout 3", "burnout", "hd", "esrgan", "racing", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_bully_textures",
        "name": "DeadOnTheInside — Bully HD Texture Pack",
        "description": (
            "HD texture replacement pack for Bully / Canis Canem Edit "
            "(SLUS-21333 / SLES-53561). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, school, and open-world textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Bully' on the creator's Patreon page. "
            "Import with Game ID SLUS-21333 (US) or SLES-53561 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Bully",
        "thumbnail_url": "",
        "tags": ["bully", "canis canem edit", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_xenosaga_textures",
        "name": "DeadOnTheInside — Xenosaga Episode I HD Texture Pack",
        "description": (
            "HD texture replacement pack for Xenosaga Episode I: Der Wille zur Macht "
            "(SLUS-20453 / SLES-51182). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, environment, and cutscene textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Xenosaga' on the creator's Patreon page. "
            "Import with Game ID SLUS-20453 (US) or SLES-51182 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Xenosaga Episode I",
        "thumbnail_url": "",
        "tags": ["xenosaga", "xenosaga episode 1", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_dmc1_textures",
        "name": "DeadOnTheInside — Devil May Cry HD Texture Pack",
        "description": (
            "HD texture replacement pack for Devil May Cry (SLUS-20216 / SLES-50291). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled castle, character, and demon textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Devil May Cry' on the creator's Patreon page. "
            "Import with Game ID SLUS-20216 (US) or SLES-50291 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Devil May Cry",
        "thumbnail_url": "",
        "tags": ["devil may cry", "dmc1", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_re_code_veronica_textures",
        "name": "DeadOnTheInside — Resident Evil: Code Veronica X HD Texture Pack",
        "description": (
            "HD texture replacement pack for Resident Evil: Code Veronica X "
            "(SLUS-20184 / SLES-50306). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled environment, character, and horror textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Code Veronica' on the creator's Patreon page. "
            "Import with Game ID SLUS-20184 (US) or SLES-50306 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Resident Evil: Code Veronica X",
        "thumbnail_url": "",
        "tags": ["resident evil code veronica", "re cvx", "hd", "esrgan", "horror", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_hack_gu_textures",
        "name": "DeadOnTheInside — .hack//G.U. HD Texture Pack",
        "description": (
            "HD texture replacement pack for .hack//G.U. Vol.1//Rebirth "
            "(SLUS-21557 / SLES-54436). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled character, dungeon, and UI textures. Free membership required."
        ),
        "context": (
            "Find the post by searching '.hack GU' on the creator's Patreon page. "
            "Import with Game ID SLUS-21557 (US) or SLES-54436 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": ".hack//G.U. Vol.1//Rebirth",
        "thumbnail_url": "",
        "tags": ["hack gu", ".hack", "hd", "esrgan", "jrpg", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_pop_sot_textures",
        "name": "DeadOnTheInside — Prince of Persia: Sands of Time HD Texture Pack",
        "description": (
            "HD texture replacement pack for Prince of Persia: The Sands of Time "
            "(SLUS-20550 / SLES-51605). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled palace, character, and environment textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Prince of Persia' on the creator's Patreon page. "
            "Import with Game ID SLUS-20550 (US) or SLES-51605 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Prince of Persia: The Sands of Time",
        "thumbnail_url": "",
        "tags": ["prince of persia", "sands of time", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_onimusha_textures",
        "name": "DeadOnTheInside — Onimusha HD Texture Pack",
        "description": (
            "HD texture replacement pack for Onimusha: Warlords "
            "(SLUS-20018 / SLES-50287). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled samurai, castle, and demon textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Onimusha' on the creator's Patreon page. "
            "Import with Game ID SLUS-20018 (US) or SLES-50287 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Onimusha: Warlords",
        "thumbnail_url": "",
        "tags": ["onimusha", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_zone_of_enders_textures",
        "name": "DeadOnTheInside — Zone of the Enders HD Texture Pack",
        "description": (
            "HD texture replacement pack for Zone of the Enders "
            "(SLUS-20234 US / SLES-50111 EU). "
            "Available on the DeadOnTheInside Patreon. "
            "Upscaled mech, environment, and battle textures. Free membership required."
        ),
        "context": (
            "Find the post by searching 'Zone of the Enders' on the creator's Patreon page. "
            "Import with Game ID SLUS-20234 (US) or SLES-50111 (EU)."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "Zone of the Enders",
        "thumbnail_url": "",
        "tags": ["zone of the enders", "zoe", "mech", "hd", "esrgan", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    # ── DeadOnTheInside — PNACH Patches ───────────────────────────────────────
    {
        "id": "doti_gow1_pnach",
        "name": "DeadOnTheInside — God of War PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for God of War (SCUS-97399). "
            "Available on the DeadOnTheInside Patreon alongside the HD texture pack. "
            "May include widescreen fix, frame-rate improvements, or gameplay tweaks."
        ),
        "context": (
            "Find the post by searching 'God of War PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "God of War",
        "thumbnail_url": "",
        "tags": ["god of war", "gow", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_kh2_pnach",
        "name": "DeadOnTheInside — Kingdom Hearts II PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for Kingdom Hearts II (SLUS-21005). "
            "Available on the DeadOnTheInside Patreon alongside the HD texture pack. "
            "May include widescreen fix, 60fps patch, or HUD improvements."
        ),
        "context": (
            "Find the post by searching 'Kingdom Hearts II PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Kingdom Hearts II",
        "thumbnail_url": "",
        "tags": ["kingdom hearts 2", "kh2", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_ffx_pnach",
        "name": "DeadOnTheInside — Final Fantasy X PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for Final Fantasy X (SLUS-20312). "
            "Available on the DeadOnTheInside Patreon. "
            "May include widescreen fix or frame-rate improvements."
        ),
        "context": (
            "Find the post by searching 'Final Fantasy X PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Final Fantasy X",
        "thumbnail_url": "",
        "tags": ["final fantasy x", "ffx", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_mgs3_pnach",
        "name": "DeadOnTheInside — Metal Gear Solid 3 PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for Metal Gear Solid 3: Snake Eater "
            "(SLUS-20718). "
            "Available on the DeadOnTheInside Patreon. "
            "May include widescreen fix, 60fps patch, or other improvements."
        ),
        "context": (
            "Find the post by searching 'MGS3 PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Metal Gear Solid 3: Snake Eater",
        "thumbnail_url": "",
        "tags": ["metal gear solid 3", "mgs3", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_re4_pnach",
        "name": "DeadOnTheInside — Resident Evil 4 PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for Resident Evil 4 (SLUS-21134). "
            "Available on the DeadOnTheInside Patreon. "
            "May include widescreen fix, frame-rate improvements, or aim-assist tweaks."
        ),
        "context": (
            "Find the post by searching 'Resident Evil 4 PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Resident Evil 4",
        "thumbnail_url": "",
        "tags": ["resident evil 4", "re4", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_sotc_pnach",
        "name": "DeadOnTheInside — Shadow of the Colossus PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for Shadow of the Colossus "
            "(SCUS-97472 / SCES-53326). "
            "Available on the DeadOnTheInside Patreon. "
            "May include widescreen fix, 60fps patch, or camera improvements."
        ),
        "context": (
            "Find the post by searching 'Shadow of the Colossus PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Shadow of the Colossus",
        "thumbnail_url": "",
        "tags": ["shadow of the colossus", "sotc", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "doti_gtasa_pnach",
        "name": "DeadOnTheInside — GTA San Andreas PNACH Patch",
        "description": (
            "Widescreen and enhancement PNACH patch for GTA: San Andreas (SLUS-20946). "
            "Available on the DeadOnTheInside Patreon. "
            "May include widescreen fix, draw-distance improvements, or mission tweaks."
        ),
        "context": (
            "Find the post by searching 'San Andreas PNACH' on the creator's Patreon page. "
            "Download the .pnach file and import via PNACH Patches → ➕ Import → 📄 File."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/c/DeadOnTheInside",
        "type": ModType.PNACH,
        "source": "Patreon",
        "game": "Grand Theft Auto: San Andreas",
        "thumbnail_url": "",
        "tags": ["gta san andreas", "gta sa", "pnach", "widescreen", "ps2", "patreon", "deadontheinside"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
        "is_free": True,
        "requires_account": True,
        "is_complete": True,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=spyro+ps2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=spyro+ps2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Spyro: Enter the Dragonfly",
        "thumbnail_url": "",
        "tags": ["spyro", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── The Legend of Spyro: A New Beginning — DurinDragon (GBAtemp) ─────────
    # Source: https://gbatemp.net/threads/the-legend-of-spyro-a-new-beginning-pcsx2-6x-upscaled-hd-texture-pack.677477/
    # Three separate variants — each has its own MediaFire download link.
    {
        "id": "spyro_anb_6x_extra_detail",
        "name": "The Legend of Spyro: A New Beginning — 6x Upscale + Extra Detail",
        "description": (
            "Full HD texture replacement pack for The Legend of Spyro: A New Beginning "
            "(SLUS-21372) by DurinDragon. "
            "6× ESRGAN upscale with extra-detail pass for sharper fine features. "
            "The largest and most detailed of the three available variants. "
            "Free download on MediaFire."
        ),
        "context": (
            "Download steps: 1) Click '⬇ Install In-App' — the app will resolve the "
            "MediaFire page and start the download automatically. "
            "2) Enter Game ID SLUS-21372 when prompted. "
            "Or visit the GBAtemp thread to see screenshots and pick a variant manually."
        ),
        "author": "DurinDragon",
        "author_url": "https://gbatemp.net/members/durindragon.778677/#recent-content",
        "is_hub": False,
        "nsfw": False,
        "url": "https://gbatemp.net/threads/the-legend-of-spyro-a-new-beginning-pcsx2-6x-upscaled-hd-texture-pack.677477/",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "The Legend of Spyro: A New Beginning",
        "thumbnail_url": "",
        "tags": ["spyro", "a new beginning", "6x", "esrgan", "extra-detail", "hd", "ps2", "gbatemp"],
        "download_action": "",
        "direct_download_url": "https://www.mediafire.com/file/y1057yt4l2ndobn/Spyro_ANB_SLUS-21372_HD_TEXTURE_PACK_6xUPSCALE_with_EXTRA_DETAIL.zip/file",
        "upscale_tech": "ESRGAN 6×",
        "is_free": True,
        "requires_account": False,
        "is_complete": True,
    },
    {
        "id": "spyro_anb_6x_only",
        "name": "The Legend of Spyro: A New Beginning — 6x Upscale Only",
        "description": (
            "HD texture replacement pack for The Legend of Spyro: A New Beginning "
            "(SLUS-21372) by DurinDragon. "
            "Pure 6× ESRGAN upscale without the extra-detail pass — smaller file size, "
            "faithful to the original art style. "
            "Free download on MediaFire."
        ),
        "context": (
            "Click '⬇ Install In-App' to auto-resolve the MediaFire page and download. "
            "Enter Game ID SLUS-21372 when prompted. "
            "Choose this variant if you want a clean upscale without additional sharpening."
        ),
        "author": "DurinDragon",
        "author_url": "https://gbatemp.net/members/durindragon.778677/#recent-content",
        "is_hub": False,
        "nsfw": False,
        "url": "https://gbatemp.net/threads/the-legend-of-spyro-a-new-beginning-pcsx2-6x-upscaled-hd-texture-pack.677477/",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "The Legend of Spyro: A New Beginning",
        "thumbnail_url": "",
        "tags": ["spyro", "a new beginning", "6x", "esrgan", "clean", "hd", "ps2", "gbatemp"],
        "download_action": "",
        "direct_download_url": "https://www.mediafire.com/file/vkkkunm8kj09bh3/Spyro_ANB_SLUS-21372_HD_Texture_Pack_ONLY_6x_UPSCALE.zip/file",
        "upscale_tech": "ESRGAN 6×",
        "is_free": True,
        "requires_account": False,
        "is_complete": True,
    },
    {
        "id": "spyro_anb_4x_anime",
        "name": "The Legend of Spyro: A New Beginning — 4x Upscale Anime Style",
        "description": (
            "HD texture replacement pack for The Legend of Spyro: A New Beginning "
            "(SLUS-21372) by DurinDragon. "
            "4× upscale using an anime-tuned ESRGAN model — vivid colours and bold lines. "
            "Best for players who prefer a stylised look over photorealism. "
            "Free download on MediaFire."
        ),
        "context": (
            "Click '⬇ Install In-App' to auto-resolve the MediaFire page and download. "
            "Enter Game ID SLUS-21372 when prompted. "
            "Choose this variant for a vibrant, cartoon-inspired aesthetic."
        ),
        "author": "DurinDragon",
        "author_url": "https://gbatemp.net/members/durindragon.778677/#recent-content",
        "is_hub": False,
        "nsfw": False,
        "url": "https://gbatemp.net/threads/the-legend-of-spyro-a-new-beginning-pcsx2-6x-upscaled-hd-texture-pack.677477/",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "The Legend of Spyro: A New Beginning",
        "thumbnail_url": "",
        "tags": ["spyro", "a new beginning", "4x", "anime", "esrgan", "hd", "ps2", "gbatemp"],
        "download_action": "",
        "direct_download_url": "https://www.mediafire.com/file/3jilfm7ahm6bs62/Spyro_ANB_SLUS-21372_HD_Texture_Pack_4x_UPSCALE_Anime_Textures.zip/file",
        "upscale_tech": "ESRGAN 4× anime",
        "is_free": True,
        "requires_account": False,
        "is_complete": True,
    },
    {
        "id": "spyro_anb_mediafire_folder",
        "name": "The Legend of Spyro: A New Beginning — All Variants (MediaFire Folder)",
        "description": (
            "MediaFire folder containing all three HD texture variants for "
            "The Legend of Spyro: A New Beginning (SLUS-21372) by DurinDragon: "
            "6x Upscale + Extra Detail, 6x Upscale Only, and 4x Anime Upscale. "
            "Visit the folder to pick and download any combination."
        ),
        "context": (
            "Open the MediaFire folder via '🌐 Visit Source' to browse all files. "
            "Then install individual ZIPs via the individual variant cards, "
            "or paste the direct zip URL into '⬇ Download from URL' in this card."
        ),
        "author": "DurinDragon",
        "author_url": "https://gbatemp.net/members/durindragon.778677/#recent-content",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.mediafire.com/folder/jpnyulhtdvd77/Spyro_A_new_Beginning_SLUS-21372",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "The Legend of Spyro: A New Beginning",
        "thumbnail_url": "",
        "tags": ["spyro", "a new beginning", "mediafire", "all-variants", "hd", "ps2", "gbatemp"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN 4×–6×",
        "is_free": True,
        "requires_account": False,
        "is_complete": True,
    },
    {
        "id": "crash_woc_textures",
        "name": "Crash Bandicoot: Wrath of Cortex — HD Textures",
        "description": (
            "HD texture replacement packs for Crash Bandicoot: The Wrath of Cortex (SLUS-20238). "
            "Community-made packs with ESRGAN-upscaled character and environment textures."
        ),
        "context": "Check GBAtemp and the PCSX2 forums for Crash texture packs — authors often list upscale model and settings.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=crash+bandicoot+ps2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=god+of+war+ps2+texture&type=downloads",
        "is_hub": True,
        "nsfw": True,
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
        "author": "",
        "author_url": "https://forums.pcsx2.net/search?q=final+fantasy+x+texture",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=kingdom+hearts+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=kingdom+hearts+2+texture&type=downloads",
        "is_hub": True,
        "nsfw": True,
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
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=shadow+colossus+texture",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=gran+turismo+4+texture&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=devil+may+cry+ps2+texture&type=downloads",
        "is_hub": True,
        "nsfw": True,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=ratchet+clank+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=jak+daxter+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=budokai+tenkaichi+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=gta+san+andreas+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
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
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=ico+texture+pack",
        "is_hub": True,
        "nsfw": False,
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
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
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
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
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "source": "GameTDB",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cover-art", "gametdb", "official", "us"],
        "download_action": "cover_by_id",
        "direct_download_url": "",
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
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "source": "GameTDB",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cover-art", "gametdb", "pal", "eu"],
        "download_action": "cover_by_id",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── New sources — GameBanana ──────────────────────────────────────────────
    {
        "id": "gamebanana_ps2",
        "name": "GameBanana — PS2 / PCSX2 Mods",
        "description": (
            "GameBanana is one of the largest game modding communities, with a growing "
            "PS2 section covering texture packs, model replacements, and patches."
        ),
        "context": (
            "Every mod page on GameBanana includes an author profile, version history, "
            "screenshots, and a direct download button. Quality varies — check ratings and comments."
        ),
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "",
        "thumbnail_url": "",
        "tags": ["community", "gamebanana", "textures", "models"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    {
        "id": "gamebanana_ps2_pnach",
        "name": "GameBanana — PS2 PNACH & Cheats",
        "description": (
            "GameBanana hosts community-made PNACH patches and cheat files for PS2 games. "
            "Browse the PS2 game section to find widescreen, 60fps and gameplay patches."
        ),
        "context": (
            "PNACH mods on GameBanana include author notes on which PCSX2 version they were "
            "tested with and which game region the patch applies to."
        ),
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/games/ps2?_aCategoryIdFilter[]=5981",
        "type": ModType.PNACH,
        "source": "GameBanana",
        "game": "",
        "thumbnail_url": "",
        "tags": ["pnach", "cheats", "gamebanana", "widescreen"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── New sources — ModDB ────────────────────────────────────────────────────
    {
        "id": "moddb_ps2",
        "name": "ModDB — PS2 Mods",
        "description": (
            "ModDB is a major modding hub with PS2 content including texture mods, "
            "gameplay patches, and total conversions."
        ),
        "context": (
            "ModDB entries include detailed author descriptions, download statistics, "
            "ratings, and comments. Good source for larger, well-documented mods."
        ),
        "author": "",
        "author_url": "https://www.moddb.com/games/ps2/mods",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.moddb.com/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "ModDB",
        "game": "",
        "thumbnail_url": "",
        "tags": ["community", "moddb", "textures"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    # ── New sources — GitHub Releases ─────────────────────────────────────────
    {
        "id": "github_ps2_textures",
        "name": "GitHub — Open-Source PS2 Texture Packs",
        "description": (
            "Several creators publish their PS2 HD texture packs as open-source "
            "GitHub repositories with versioned releases. These are freely available "
            "with detailed changelogs."
        ),
        "context": (
            "Search GitHub for 'ps2 texture pack pcsx2' to find open-source packs. "
            "Download the latest release ZIP and install it using the Import button "
            "in the Texture Packs panel."
        ),
        "author": "",
        "author_url": "https://github.com/search?q=ps2+texture+pack+pcsx2&type=repositories",
        "is_hub": True,
        "nsfw": False,
        "url": "https://github.com/search?q=ps2+texture+pack+pcsx2&type=repositories",
        "type": ModType.TEXTURE_PACK,
        "source": "GitHub",
        "game": "",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["github", "open-source", "textures", "hd"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    # ── Game-Specific — Silent Hill series ────────────────────────────────────
    {
        "id": "sh2_textures",
        "name": "Silent Hill 2 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Silent Hill 2 (SLUS-20228). "
            "Upscaled fog, environment, character and monster textures."
        ),
        "context": (
            "Silent Hill 2's atmospheric fog and lighting make HD textures very impactful. "
            "Check GBAtemp and PSX-Place for author-credited packs with settings recommendations."
        ),
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=silent+hill+2+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=silent+hill+2+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Silent Hill 2",
        "thumbnail_url": "",
        "tags": ["silent-hill", "sh2", "horror", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "sh3_textures",
        "name": "Silent Hill 3 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Silent Hill 3 (SLUS-20622). "
            "Upscaled environments, character and UI textures."
        ),
        "context": "SH3 has vibrant colours that upscale very well. Find packs on GBAtemp and PSX-Place.",
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "type": ModType.TEXTURE_PACK,
        "source": "PSX-Place",
        "game": "Silent Hill 3",
        "thumbnail_url": "",
        "tags": ["silent-hill", "sh3", "horror", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / Waifu2x",
    },
    # ── Game-Specific — Metal Gear Solid series ────────────────────────────────
    {
        "id": "mgs3_textures",
        "name": "Metal Gear Solid 3 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Metal Gear Solid 3: Snake Eater (SLUS-20763). "
            "Upscaled jungle, character and equipment textures."
        ),
        "context": "One of the most-requested PS2 texture projects. Check GBAtemp and LoversLab for Snake Eater and Subsistence packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=metal+gear+solid+3+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=metal+gear+solid+3+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Metal Gear Solid 3: Snake Eater",
        "thumbnail_url": "",
        "tags": ["mgs3", "metal-gear", "hd", "stealth", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "mgs3_widescreen_pnach",
        "name": "Metal Gear Solid 3 — Widescreen + 60fps Patches",
        "description": (
            "Widescreen (16:9) and 60fps PNACH patches for Metal Gear Solid 3: "
            "Snake Eater (SLUS-20763). From the PCSX2 widescreen patches repository."
        ),
        "context": "Fetch this patch directly using the '🔧 Fetch PNACH from GitHub' button and enter the game CRC.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Metal Gear Solid 3",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "mgs3", "metal-gear", "60fps", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Game-Specific — Persona series ───────────────────────────────────────
    {
        "id": "persona3_textures",
        "name": "Persona 3 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Persona 3 / FES (SLUS-21224 / SLUS-21621). "
            "Upscaled UI, character portraits and environment textures."
        ),
        "context": "Persona 3's stylised UI and anime art style upscale beautifully with Waifu2x. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=persona+3+texture+ps2&type=downloads",
        "is_hub": True,
        "nsfw": True,
        "url": "https://www.loverslab.com/search/#q=persona+3+texture+ps2&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Persona 3 / FES",
        "thumbnail_url": "",
        "tags": ["persona", "persona3", "atlus", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x / ESRGAN (anime)",
    },
    {
        "id": "persona4_textures",
        "name": "Persona 4 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Persona 4 (SLUS-21782). "
            "Upscaled UI, character and dungeon textures. "
            "Makes the game look substantially better on modern displays."
        ),
        "context": "Multiple authors have published P4 texture packs on GBAtemp and LoversLab. Look for packs that cover both the dungeon and social link scenes.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=persona+4+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=persona+4+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Persona 4",
        "thumbnail_url": "",
        "tags": ["persona", "persona4", "atlus", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x / ESRGAN (anime)",
    },
    # ── Game-Specific — Okami ────────────────────────────────────────────────
    {
        "id": "okami_textures",
        "name": "Okami — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Okami (SLUS-21418). "
            "Upscaled ink-wash art style textures — characters, environments and brush effects."
        ),
        "context": "Okami's unique cel-shaded art style responds remarkably well to texture upscaling. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=okami+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=okami+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Okami",
        "thumbnail_url": "",
        "tags": ["okami", "capcom", "cel-shaded", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── Game-Specific — Resident Evil series ─────────────────────────────────
    {
        "id": "re4_textures",
        "name": "Resident Evil 4 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Resident Evil 4 (SLUS-21134). "
            "Upscaled character, environment and item textures."
        ),
        "context": "RE4 is widely modded. Check GBAtemp, LoversLab and GameBanana for texture packs. Many authors recommend Vulkan renderer with 4× resolution.",
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=resident+evil+4+ps2+texture&type=downloads",
        "is_hub": True,
        "nsfw": True,
        "url": "https://www.loverslab.com/search/#q=resident+evil+4+ps2+texture&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Resident Evil 4",
        "thumbnail_url": "",
        "tags": ["resident-evil", "re4", "capcom", "survival-horror", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "re4_widescreen_pnach",
        "name": "Resident Evil 4 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Resident Evil 4 (SLUS-21134). "
            "Removes black bars and enables true 16:9 gameplay."
        ),
        "context": "Grab this patch from the PCSX2 widescreen patches GitHub using the '🔧 Fetch PNACH from GitHub' button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Resident Evil 4",
        "thumbnail_url": "",
        "tags": ["widescreen", "resident-evil", "re4", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Game-Specific — Prince of Persia / Tekken / WWE ───────────────────────
    {
        "id": "pop_sot_textures",
        "name": "Prince of Persia: Sands of Time — HD Textures",
        "description": (
            "Community HD texture replacements for Prince of Persia: The Sands of Time (SLUS-20743). "
            "Upscaled palace, desert, and character textures."
        ),
        "context": "Check GBAtemp and PSX-Place for PoP texture packs. The game's rich colour palette upscales well.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=prince+of+persia+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=prince+of+persia+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Prince of Persia: Sands of Time",
        "thumbnail_url": "",
        "tags": ["prince-of-persia", "ubisoft", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "tekken5_textures",
        "name": "Tekken 5 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Tekken 5 (SLUS-21059). "
            "Upscaled character, stage and UI textures."
        ),
        "context": "Tekken 5 is one of the best-looking PS2 games and its textures upscale very well. Find packs on GBAtemp and GameBanana.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "Tekken 5",
        "thumbnail_url": "",
        "tags": ["tekken5", "bandai-namco", "fighting", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "burnout3_textures",
        "name": "Burnout 3: Takedown — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Burnout 3: Takedown (SLUS-20872). "
            "Upscaled car liveries, track environments and menu textures."
        ),
        "context": "Burnout 3's high-speed action benefits enormously from HD textures. Check GBAtemp and Reddit r/ps2.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=burnout+3+texture",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=burnout+3+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Burnout 3: Takedown",
        "thumbnail_url": "",
        "tags": ["burnout3", "racing", "ea", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── Game-Specific — GTA Vice City ─────────────────────────────────────────
    {
        "id": "gtavc_textures",
        "name": "GTA Vice City — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Grand Theft Auto: Vice City (SLUS-20552). "
            "Upscaled city, vehicle and character textures."
        ),
        "context": "Vice City's 80s aesthetic and dense city blocks are transformed by HD textures. Check GBAtemp and Reddit for the latest packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=gta+vice+city+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=gta+vice+city+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "GTA Vice City",
        "thumbnail_url": "",
        "tags": ["gta", "vice-city", "open-world", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── Game-Specific — More PNACH patches ───────────────────────────────────
    {
        "id": "dbz_bt3_pnach",
        "name": "Dragon Ball Z: Budokai Tenkaichi 3 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for DBZ Budokai Tenkaichi 3 (SLUS-21678). "
            "Enables native 16:9 output for a better viewing experience."
        ),
        "context": "Get the widescreen patch from the PCSX2 GitHub using the 🔧 Fetch PNACH button and entering your game CRC.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Dragon Ball Z: Budokai Tenkaichi 3",
        "thumbnail_url": "",
        "tags": ["widescreen", "dbz", "dragon-ball", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "jak2_widescreen_pnach",
        "name": "Jak II & Jak 3 — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for Jak II (SCUS-97265) and Jak 3 (SCUS-97330). "
            "Enable 16:9 widescreen output."
        ),
        "context": "The Jak series widescreen patches are well-maintained. Fetch from the PCSX2 GitHub using the 🔧 button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Jak II / Jak 3",
        "thumbnail_url": "",
        "tags": ["widescreen", "jak", "naughty-dog", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "ratchet_clank_pnach",
        "name": "Ratchet & Clank — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for the Ratchet & Clank series on PS2. "
            "Covers R&C (SCUS-97199), Going Commando (SCUS-97268) and Up Your Arsenal (SCUS-97353)."
        ),
        "context": "Fetch these from the PCSX2 GitHub. Enter your specific game's CRC in the 🔧 PNACH fetcher.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Ratchet & Clank series",
        "thumbnail_url": "",
        "tags": ["widescreen", "ratchet-clank", "insomniac", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "persona3_pnach",
        "name": "Persona 3 FES — Widescreen + Misc Patches",
        "description": (
            "PNACH patches for Persona 3 FES (SLUS-21621) including widescreen, "
            "battle speed boosts, and UI fixes."
        ),
        "context": "Community patches collected in the GBAtemp PS2 PNACH thread. Author info and version notes included.",
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=persona+3&t=file_update",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/3519/?q=persona+3&t=file_update",
        "type": ModType.PNACH,
        "source": "GBAtemp",
        "game": "Persona 3 FES",
        "thumbnail_url": "",
        "tags": ["persona", "widescreen", "pnach", "jrpg"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Community Cheat Databases ─────────────────────────────────────────────
    {
        "id": "ps2rd_cheatdb",
        "name": "PS2RD — PS2 Reality Cheat Database",
        "description": (
            "PS2RD hosts a comprehensive community cheat database for PS2 games "
            "in multiple formats including PNACH. Includes rare region-specific codes."
        ),
        "context": "PNACH-format cheats compatible with PCSX2 cheats folder. Author credits and game CRCs included.",
        "author": "",
        "author_url": "https://github.com/PCSX2/cheatdb",
        "is_hub": True,
        "nsfw": False,
        "url": "https://github.com/PCSX2/cheatdb",
        "type": ModType.CHEAT,
        "source": "GitHub",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "pnach", "database", "community"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "reddit_ps2_cheats",
        "name": "r/ps2 — Cheats & PNACH Patches",
        "description": (
            "Reddit r/ps2 community shares PNACH patches, cheat codes and "
            "game-specific patches. Authors post regional compatibility info."
        ),
        "context": "Community-validated cheats. Check post date for PCSX2 version compatibility.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=pnach+cheat&sort=new",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=pnach+cheat&sort=new",
        "type": ModType.CHEAT,
        "source": "Reddit",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "pnach", "community", "reddit"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "gamefaqs_cheats",
        "name": "GameFAQs — PS2 Cheat Codes",
        "description": (
            "GameFAQs maintains one of the most comprehensive PS2 cheat code databases. "
            "Codes can be converted to PNACH format for use with PCSX2."
        ),
        "context": "GameFAQs codes are in GameShark / CodeBreaker format. The PNACH Panel can import and auto-convert these.",
        "author": "",
        "author_url": "https://gamefaqs.gamespot.com/ps2/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamefaqs.gamespot.com/ps2/",
        "type": ModType.CHEAT,
        "source": "GameFAQs",
        "game": "",
        "thumbnail_url": "https://gamefaqs.gamespot.com/favicon.ico",
        "tags": ["cheats", "gameshark", "community"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── More Save File Sources ────────────────────────────────────────────────
    {
        "id": "archive_org_saves",
        "name": "Internet Archive — PS2 Save Files",
        "description": (
            "The Internet Archive hosts collections of PS2 save files contributed "
            "by the community. Good source for 100% completion saves and maxed-out profiles."
        ),
        "context": "Search for specific game titles to find relevant saves. Import using the Memory Card panel.",
        "author": "",
        "author_url": "https://archive.org/search?query=ps2+save+file&mediatype=data",
        "is_hub": True,
        "nsfw": False,
        "url": "https://archive.org/search?query=ps2+save+file&mediatype=data",
        "type": ModType.SAVE_FILE,
        "source": "Archive.org",
        "game": "",
        "thumbnail_url": "",
        "tags": ["saves", "archive", "100-percent"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "reddit_ps2_saves",
        "name": "r/ps2 — Save Files",
        "description": (
            "Reddit r/ps2 users share game save files for progress sharing, "
            "unlocking extras, and helping with difficult sections."
        ),
        "context": "Check the post for region info (NTSC-U / PAL) before downloading — saves are region-locked.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=save+file&sort=new",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=save+file&sort=new",
        "type": ModType.SAVE_FILE,
        "source": "Reddit",
        "game": "",
        "thumbnail_url": "",
        "tags": ["saves", "community", "reddit"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── New texture resource — Archive.org ───────────────────────────────────
    {
        "id": "archive_org_textures",
        "name": "Internet Archive — PS2 Texture Packs",
        "description": (
            "The Internet Archive hosts community-uploaded PS2 HD texture packs "
            "in freely accessible ZIP archives. A great long-term preservation source."
        ),
        "context": "Direct ZIP downloads available — use the '⬇ Download from URL' button with the Archive.org direct link.",
        "author": "",
        "author_url": "https://archive.org/search?query=ps2+hd+texture+pack+pcsx2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://archive.org/search?query=ps2+hd+texture+pack+pcsx2",
        "type": ModType.TEXTURE_PACK,
        "source": "Archive.org",
        "game": "",
        "thumbnail_url": "",
        "tags": ["textures", "archive", "hd", "free"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    # ── PCSX2 Community Forum specific threads ────────────────────────────────
    {
        "id": "pcsx2_60fps_patches",
        "name": "PCSX2 60fps Frame Rate Patches",
        "description": (
            "Community-maintained collection of 60fps frame rate PNACH patches "
            "for PS2 games. Many popular titles have been modded to run at 60fps."
        ),
        "context": (
            "60fps patches work at the PNACH level — no emulator settings needed. "
            "Author attribution and game CRCs are included in each file."
        ),
        "author": "",
        "author_url": "https://forums.pcsx2.net/search?q=60fps+patch&type=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/search?q=60fps+patch&type=post",
        "type": ModType.PNACH,
        "source": "PCSX2 Forums",
        "game": "",
        "thumbnail_url": "https://pcsx2.net/favicon.ico",
        "tags": ["60fps", "patches", "pnach", "performance"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "pcsx2_analog_patches",
        "name": "PCSX2 Analog / HUD Fix Patches",
        "description": (
            "PNACH patches that fix HUD scaling, aspect ratio and analogue input issues "
            "for PS2 games when played on PCSX2 with widescreen enabled."
        ),
        "context": "Often bundled with widescreen patches. Look for posts labelled 'HUD fix' or 'widescreen HUD correction'.",
        "author": "",
        "author_url": "https://forums.pcsx2.net/search?q=hud+fix+widescreen&type=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/search?q=hud+fix+widescreen&type=post",
        "type": ModType.PNACH,
        "source": "PCSX2 Forums",
        "game": "",
        "thumbnail_url": "",
        "tags": ["hud-fix", "widescreen", "patches", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── More game-specific texture packs ─────────────────────────────────────
    {
        "id": "naruto_uzumaki_textures",
        "name": "Naruto: Uzumaki Chronicles — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Naruto: Uzumaki Chronicles (SLUS-21162). "
            "Upscaled character, jutsu effect and environment textures."
        ),
        "context": "Naruto's distinctive anime art style responds very well to Waifu2x upscaling. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=naruto+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=naruto+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Naruto: Uzumaki Chronicles",
        "thumbnail_url": "",
        "tags": ["naruto", "bandai-namco", "anime", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x / ESRGAN (anime)",
    },
    {
        "id": "naruto_uns_textures",
        "name": "Naruto: Ultimate Ninja Storm — HD Textures (PS2 originals)",
        "description": (
            "Community HD textures for the PS2 Naruto Ultimate Ninja series. "
            "Upscaled character portraits, jutsu effects and stage backgrounds."
        ),
        "context": "Search GameBanana and GBAtemp for Naruto Ultimate Ninja HD mods. The anime cel-shaded style benefits greatly from Waifu2x.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "Naruto: Ultimate Ninja series",
        "thumbnail_url": "",
        "tags": ["naruto", "bandai-namco", "anime", "fighting", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x (anime)",
    },
    {
        "id": "wwe_smackdown_textures",
        "name": "WWE SmackDown vs. Raw — HD Texture Pack",
        "description": (
            "Community HD textures for WWE SmackDown vs. Raw 2006/2007/2008 (SLUS-21358 etc). "
            "Upscaled wrestler portraits, arena and crowd textures."
        ),
        "context": "One of the most popular PS2 wrestling games for modding. Check GameBanana and GBAtemp for packs with specific wrestler rosters.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "WWE SmackDown vs. Raw",
        "thumbnail_url": "",
        "tags": ["wwe", "wrestling", "thq", "sports", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "bully_textures",
        "name": "Bully — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Bully / Canis Canem Edit (SLUS-21269). "
            "Upscaled character, campus and town environment textures."
        ),
        "context": "Bully's rich open world benefits greatly from HD textures. Check GBAtemp and Reddit for community packs.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=bully+texture+pack",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=bully+texture+pack",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Bully / Canis Canem Edit",
        "thumbnail_url": "",
        "tags": ["bully", "rockstar", "open-world", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "nfs_mw_textures",
        "name": "Need for Speed: Most Wanted — HD Texture Pack",
        "description": (
            "Community HD textures for Need for Speed: Most Wanted (SLUS-21108). "
            "Upscaled car liveries, city environment and menu textures."
        ),
        "context": "NFS Most Wanted is one of the most played PS2 racing games. Check GBAtemp and GameBanana for community texture packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=need+for+speed+most+wanted+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=need+for+speed+most+wanted+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Need for Speed: Most Wanted",
        "thumbnail_url": "",
        "tags": ["nfs", "most-wanted", "racing", "ea", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "nfs_underground2_textures",
        "name": "Need for Speed: Underground 2 — HD Texture Pack",
        "description": (
            "Community HD texture replacements for NFS Underground 2 (SLUS-20967). "
            "Upscaled car customisation, city streets and neon environment textures."
        ),
        "context": "NFS Underground 2 has a large modding community. Check GameBanana and GBAtemp for car livery and environment packs.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "Need for Speed: Underground 2",
        "thumbnail_url": "",
        "tags": ["nfs", "underground", "racing", "ea", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "god_hand_textures",
        "name": "God Hand — HD Texture Pack",
        "description": (
            "Community HD texture replacements for God Hand (SLUS-21503). "
            "Upscaled character, demon and environment textures for this cult classic."
        ),
        "context": "God Hand's cartoon-ish 3D style upscales nicely. Find packs on PSX-Place and GBAtemp.",
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "type": ModType.TEXTURE_PACK,
        "source": "PSX-Place",
        "game": "God Hand",
        "thumbnail_url": "",
        "tags": ["god-hand", "capcom", "action", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "viewtiful_joe_textures",
        "name": "Viewtiful Joe — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Viewtiful Joe (SLUS-20590). "
            "Upscaled cel-shaded character and stage textures."
        ),
        "context": "Viewtiful Joe's bold cel-shading style makes it excellent for HD upscaling. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=viewtiful+joe+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=viewtiful+joe+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Viewtiful Joe",
        "thumbnail_url": "",
        "tags": ["viewtiful-joe", "capcom", "cel-shaded", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "xenosaga_textures",
        "name": "Xenosaga Episode I — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Xenosaga Episode I (SLUS-20469). "
            "Upscaled character portrait, cutscene and battle textures."
        ),
        "context": "Xenosaga's anime-adjacent art style responds very well to Waifu2x. Check GBAtemp and LoversLab for episode I–III packs.",
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=xenosaga+texture+ps2&type=downloads",
        "is_hub": True,
        "nsfw": True,
        "url": "https://www.loverslab.com/search/#q=xenosaga+texture+ps2&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Xenosaga Episode I",
        "thumbnail_url": "",
        "tags": ["xenosaga", "bandai-namco", "jrpg", "sci-fi", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x / ESRGAN (anime)",
    },
    {
        "id": "dragon_quest_viii_textures",
        "name": "Dragon Quest VIII — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Dragon Quest VIII (SLUS-21005 / SLUS-21265). "
            "Upscaled character, environment and monster textures."
        ),
        "context": "DQ VIII's vibrant cel-shaded art style benefits enormously from ESRGAN upscaling. Check GBAtemp for community packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=dragon+quest+viii+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=dragon+quest+viii+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Dragon Quest VIII",
        "thumbnail_url": "",
        "tags": ["dragon-quest", "dq8", "square-enix", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN (anime model)",
    },
    {
        "id": "star_ocean_3_textures",
        "name": "Star Ocean: Till the End of Time — HD Textures",
        "description": (
            "Community HD texture replacements for Star Ocean 3 (SLUS-20362). "
            "Upscaled character portraits, battle and world map textures."
        ),
        "context": "SO3 has very detailed environments that upscale well. Check GBAtemp and PCSX2 Forums for community packs.",
        "author": "",
        "author_url": "https://forums.pcsx2.net/search?q=star+ocean+texture",
        "is_hub": True,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/search?q=star+ocean+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "PCSX2 Forums",
        "game": "Star Ocean: Till the End of Time",
        "thumbnail_url": "",
        "tags": ["star-ocean", "square-enix", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "sly_cooper_textures",
        "name": "Sly Cooper — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Sly Cooper and the Thievius Raccoonus (SCUS-97198) "
            "and its sequels. Upscaled cel-shaded character and environment textures."
        ),
        "context": "Sly's bold cartoon style upscales beautifully. Check GBAtemp for packs covering all three PS2 Sly games.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=sly+cooper+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=sly+cooper+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Sly Cooper series",
        "thumbnail_url": "",
        "tags": ["sly-cooper", "sucker-punch", "platformer", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "xBRZ / ESRGAN",
    },
    {
        "id": "katamari_textures",
        "name": "Katamari Damacy — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Katamari Damacy (SLUS-20917). "
            "Upscaled objects, environment and UI textures for the quirky cult classic."
        ),
        "context": "Katamari's colorful distinct art style lends itself perfectly to texture upscaling. Check GBAtemp and Reddit r/ps2.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=katamari+texture",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=katamari+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Katamari Damacy",
        "thumbnail_url": "",
        "tags": ["katamari", "bandai-namco", "puzzle", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "xBRZ / ESRGAN",
    },
    {
        "id": "ff12_textures",
        "name": "Final Fantasy XII — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Final Fantasy XII (SLUS-20963). "
            "Upscaled characters, Ivalice environment and UI textures."
        ),
        "context": "FF12 is a popular target for texture mods due to its large open world. Check GBAtemp and PCSX2 Forums for community packs.",
        "author": "",
        "author_url": "https://forums.pcsx2.net/search?q=final+fantasy+xii+texture",
        "is_hub": True,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/search?q=final+fantasy+xii+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "PCSX2 Forums",
        "game": "Final Fantasy XII",
        "thumbnail_url": "",
        "tags": ["final-fantasy", "ff12", "square-enix", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / Waifu2x",
    },
    {
        "id": "mgs2_textures",
        "name": "Metal Gear Solid 2: Sons of Liberty — HD Textures",
        "description": (
            "Community HD texture replacements for Metal Gear Solid 2 (SLUS-20144). "
            "Upscaled environment, character and codec textures."
        ),
        "context": "MGS2's highly detailed environments respond extremely well to ESRGAN upscaling. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://www.loverslab.com/search/#q=metal+gear+solid+2+texture&type=downloads",
        "is_hub": True,
        "nsfw": True,
        "url": "https://www.loverslab.com/search/#q=metal+gear+solid+2+texture&type=downloads",
        "type": ModType.TEXTURE_PACK,
        "source": "LoversLab",
        "game": "Metal Gear Solid 2",
        "thumbnail_url": "",
        "tags": ["mgs2", "metal-gear", "konami", "stealth", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "tony_hawk_textures",
        "name": "Tony Hawk's Pro Skater — HD Texture Pack",
        "description": (
            "Community HD textures for Tony Hawk's Pro Skater 3/4 on PS2. "
            "Upscaled skate park environments, character and trick effect textures."
        ),
        "context": "THPS games have vibrant environments that upscale nicely. Check GBAtemp and GameBanana for packs.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "Tony Hawk's Pro Skater series",
        "thumbnail_url": "",
        "tags": ["tony-hawk", "activision", "sports", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── More game-specific PNACH patches ─────────────────────────────────────
    {
        "id": "okami_widescreen_pnach",
        "name": "Okami — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Okami (SLUS-21418). "
            "Enables true 16:9 output to match the beautiful ink-wash art style."
        ),
        "context": "Fetch this patch from the PCSX2 GitHub widescreen patches repo using the 🔧 PNACH button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Okami",
        "thumbnail_url": "",
        "tags": ["widescreen", "okami", "capcom", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "bully_widescreen_pnach",
        "name": "Bully / Canis Canem Edit — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Bully (SLUS-21269 / SLES-53561). "
            "Removes black bars for a proper 16:9 experience."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches using the 🔧 PNACH button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Bully / Canis Canem Edit",
        "thumbnail_url": "",
        "tags": ["widescreen", "bully", "rockstar", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "nfs_mw_widescreen_pnach",
        "name": "Need for Speed: Most Wanted — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for NFS Most Wanted (SLUS-21108). "
            "Corrects aspect ratio for modern widescreen monitors."
        ),
        "context": "Get from the PCSX2 widescreen patches GitHub using the 🔧 button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Need for Speed: Most Wanted",
        "thumbnail_url": "",
        "tags": ["widescreen", "nfs", "racing", "ea", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "gta3_widescreen_pnach",
        "name": "GTA III — Widescreen + 60fps Patches",
        "description": (
            "Widescreen and 60fps PNACH patches for GTA III (SLUS-20062). "
            "Enables 16:9 output and smoother gameplay."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches using the 🔧 PNACH button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "GTA III",
        "thumbnail_url": "",
        "tags": ["widescreen", "gta", "rockstar", "60fps", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "spiderman_2_widescreen_pnach",
        "name": "Spider-Man 2 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Spider-Man 2 (SLUS-20776). "
            "Corrects the aspect ratio for a proper widescreen experience."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches using the 🔧 PNACH button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Spider-Man 2",
        "thumbnail_url": "",
        "tags": ["widescreen", "spider-man", "activision", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── More cheats/patches ───────────────────────────────────────────────────
    {
        "id": "pcsx2_unlock_patches",
        "name": "PCSX2 Unlock / Debug Patches",
        "description": (
            "PNACH patches that unlock hidden content, developer modes, and debug menus "
            "for various PS2 games. Great for exploring cut content."
        ),
        "context": "Found on GBAtemp and the PCSX2 forums. Author notes usually explain what each patch does and its game region.",
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=unlock+debug&t=file_update",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/3519/?q=unlock+debug&t=file_update",
        "type": ModType.CHEAT,
        "source": "GBAtemp",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "unlock", "debug", "pnach", "hidden-content"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "archive_org_ps2_cheats",
        "name": "Internet Archive — PS2 Cheat Code Collections",
        "description": (
            "The Internet Archive hosts community-preserved PS2 cheat code books, "
            "GameShark and CodeBreaker code collections in various formats."
        ),
        "context": "Raw cheat codes in AR2/CodeBreaker format. The PNACH panel can import and convert many of these.",
        "author": "",
        "author_url": "https://archive.org/search?query=ps2+cheat+codes&mediatype=texts",
        "is_hub": True,
        "nsfw": False,
        "url": "https://archive.org/search?query=ps2+cheat+codes&mediatype=texts",
        "type": ModType.CHEAT,
        "source": "Archive.org",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "gameshark", "archive", "collection"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── More save file entries ────────────────────────────────────────────────
    {
        "id": "gbatemp_saves",
        "name": "GBAtemp — PS2 Save Files",
        "description": (
            "GBAtemp hosts community-submitted PS2 save files with region and "
            "version notes. Authors often include completion percentage and unlock info."
        ),
        "context": "Check the author's post for region info (NTSC-U / PAL). Save files are region-locked so the right version matters.",
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=ps2+save&t=file_update",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/3519/?q=ps2+save&t=file_update",
        "type": ModType.SAVE_FILE,
        "source": "GBAtemp",
        "game": "",
        "thumbnail_url": "https://gbatemp.net/styles/gbatemp/logo.png",
        "tags": ["saves", "community", "gbatemp"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Cover art additions ───────────────────────────────────────────────────
    {
        "id": "mobygames_covers",
        "name": "MobyGames — PS2 Cover Art",
        "description": (
            "MobyGames maintains a comprehensive database of PS2 game cover art, "
            "screenshots, and metadata. Excellent for finding regional cover variants."
        ),
        "context": "High-resolution box art from multiple regions. Useful for finding Japanese, European and Australian variants.",
        "author": "",
        "author_url": "https://www.mobygames.com/game/platform:ps2/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.mobygames.com/game/platform:ps2/",
        "type": ModType.COVER_ART,
        "source": "MobyGames",
        "game": "",
        "thumbnail_url": "",
        "tags": ["covers", "art", "database", "regional"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "screenscraper_covers",
        "name": "ScreenScraper — PS2 Media Database",
        "description": (
            "ScreenScraper is a community scraping database with PS2 box art, "
            "screenshots, manuals and fanart. Free API for personal use."
        ),
        "context": "Used by EmulationStation and other frontends. Box art is available in multiple resolutions and regional variants.",
        "author": "",
        "author_url": "https://www.screenscraper.fr/gameinfos.php?plateforme=57",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.screenscraper.fr/gameinfos.php?plateforme=57",
        "type": ModType.COVER_ART,
        "source": "ScreenScraper",
        "game": "",
        "thumbnail_url": "",
        "tags": ["covers", "art", "screenscraper", "community"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Additional Texture Pack Sources ──────────────────────────────────────
    {
        "id": "pcsx2_official_textures",
        "name": "PCSX2 Official Texture Replacement Forum",
        "description": (
            "The official PCSX2 forums host threads dedicated to texture replacement "
            "packs submitted by the community. This is the primary hub for PS2 HD "
            "texture packs with PCSX2-specific compatibility notes."
        ),
        "context": "Each thread is game-specific; authors include compatibility notes, recommended PCSX2 settings, and upscale method details.",
        "author": "",
        "author_url": "https://forums.pcsx2.net/Forum-Texture-Packs",
        "is_hub": True,
        "nsfw": False,
        "url": "https://forums.pcsx2.net/Forum-Texture-Packs",
        "type": ModType.TEXTURE_PACK,
        "source": "PCSX2 Forums",
        "game": "",
        "thumbnail_url": "https://pcsx2.net/favicon.ico",
        "tags": ["official", "community", "textures", "hd"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    {
        "id": "discord_ps2_textures",
        "name": "PCSX2 Discord — Texture Mods Channel",
        "description": (
            "The official PCSX2 Discord server has a dedicated channel for texture "
            "mod creators and users to share packs, ask for help, and get support."
        ),
        "context": "Discord is where many new texture packs are announced first. Check #texture-packs channel for the latest releases.",
        "author": "",
        "author_url": "https://discord.gg/TCz3t9T",
        "is_hub": True,
        "nsfw": False,
        "url": "https://discord.gg/TCz3t9T",
        "type": ModType.TEXTURE_PACK,
        "source": "Discord",
        "game": "",
        "thumbnail_url": "",
        "tags": ["discord", "community", "textures", "hd"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Various",
    },
    # ── WIDESCREEN / PNACH: Widescreen Hack Database ─────────────────────────
    {
        "id": "pcsx2_patches_github_direct",
        "name": "PCSX2 Widescreen Patches — Full Repository",
        "description": (
            "Direct link to all official widescreen PNACH patches in the PCSX2 "
            "GitHub repository. Over 500 patches covering virtually every popular PS2 game."
        ),
        "context": (
            "Use the '🔧 Fetch PNACH from GitHub' button in this panel to search by "
            "game CRC and install patches directly. Alternatively browse the repo and "
            "download individual .pnach files."
        ),
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "official", "open-source", "all-games"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_full_db",
        "name": "PS2Wide — Complete Widescreen Hack Database",
        "description": (
            "PS2Wide.net maintains the most comprehensive widescreen hack database "
            "for PS2 games with 300+ titles. Individual PNACH download links available."
        ),
        "context": "Navigate to the PS2 section, find your game, and download the .pnach file. Then import it using the PNACH panel.",
        "author": "nemesis2090 (PS2Wide)",
        "author_url": "https://gbatemp.net/members/nemesis2090.27154/",
        "is_hub": False,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "All Games",
        "thumbnail_url": "",
        "tags": ["widescreen", "pnach", "16:9", "all-games", "ps2wide"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Game-Specific: More Texture Packs ────────────────────────────────────
    {
        "id": "gow2_textures",
        "name": "God of War II — HD Texture Pack",
        "description": (
            "Community HD texture replacements for God of War II (SCUS-97402). "
            "Upscaled character, environment and enemy textures."
        ),
        "context": "God of War II has exceptional texture quality for a PS2 game. ESRGAN upscaling enhances it further. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=god+of+war+2+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=god+of+war+2+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "God of War II",
        "thumbnail_url": "",
        "tags": ["god-of-war", "gow2", "action", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "dmc1_textures",
        "name": "Devil May Cry — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Devil May Cry (SLUS-20216). "
            "Upscaled character, castle and demon textures."
        ),
        "context": "The original DMC's gothic style upscales very well. Check GBAtemp and LoversLab for packs. Pair with widescreen patch for best results.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=devil+may+cry+1+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=devil+may+cry+1+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Devil May Cry",
        "thumbnail_url": "",
        "tags": ["devil-may-cry", "dmc1", "capcom", "action", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "re_code_veronica_textures",
        "name": "Resident Evil: Code Veronica X — HD Textures",
        "description": (
            "Community HD texture replacements for Resident Evil: Code Veronica X (SLUS-20184). "
            "Upscaled pre-rendered backgrounds, characters and item textures."
        ),
        "context": "CVX's pre-rendered backgrounds are surprisingly receptive to HD upscaling. Check GBAtemp and PSX-Place for packs.",
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.psx-place.com/resources/categories/ps2-mods.18/",
        "type": ModType.TEXTURE_PACK,
        "source": "PSX-Place",
        "game": "Resident Evil: Code Veronica X",
        "thumbnail_url": "",
        "tags": ["resident-evil", "re-cvx", "capcom", "survival-horror", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "onimusha_textures",
        "name": "Onimusha: Warlords — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Onimusha: Warlords (SLUS-20015). "
            "Upscaled feudal Japanese environment, samurai and demon textures."
        ),
        "context": "Onimusha's detailed feudal Japan settings upscale very well. Check GBAtemp and PSX-Place for community packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=onimusha+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=onimusha+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Onimusha: Warlords",
        "thumbnail_url": "",
        "tags": ["onimusha", "capcom", "action", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "zone_of_enders_textures",
        "name": "Zone of the Enders — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Zone of the Enders (SLUS-20128) "
            "and ZOE: 2nd Runner (SLUS-20554). Upscaled mecha and space environment textures."
        ),
        "context": "ZOE's futuristic art style and high-contrast mecha designs upscale beautifully. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=zone+of+enders+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=zone+of+enders+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Zone of the Enders",
        "thumbnail_url": "",
        "tags": ["zone-of-enders", "zoe", "konami", "mecha", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "dark_cloud_textures",
        "name": "Dark Cloud / Dark Chronicle — HD Textures",
        "description": (
            "Community HD texture replacements for Dark Cloud (SCUS-97111) and "
            "Dark Cloud 2 / Dark Chronicle (SCUS-97213). Upscaled environment, "
            "character and dungeon textures."
        ),
        "context": "Dark Cloud 2's vibrant cartoon style makes it a favourite for HD texture mods. Check GBAtemp and PSX-Place.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=dark+cloud+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=dark+cloud+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Dark Cloud / Dark Chronicle",
        "thumbnail_url": "",
        "tags": ["dark-cloud", "level5", "rpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "soul_calibur_textures",
        "name": "SoulCalibur II / III — HD Texture Packs",
        "description": (
            "Community HD texture replacements for SoulCalibur II (SLUS-20591) and "
            "SoulCalibur III (SLUS-21216). Upscaled fighter, stage and weapon textures."
        ),
        "context": "SoulCalibur's highly detailed character models and stages are transformed by HD textures. Check GBAtemp and GameBanana.",
        "author": "",
        "author_url": "https://gamebanana.com/mods/games/ps2",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gamebanana.com/mods/games/ps2",
        "type": ModType.TEXTURE_PACK,
        "source": "GameBanana",
        "game": "SoulCalibur II / III",
        "thumbnail_url": "",
        "tags": ["soulcalibur", "bandai-namco", "fighting", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "hack_gu_textures",
        "name": ".hack//G.U. — HD Texture Pack",
        "description": (
            "Community HD texture replacements for the .hack//G.U. trilogy (SLUS-21434+). "
            "Upscaled character, dungeon and UI textures from the beloved JRPG series."
        ),
        "context": ".hack//GU's anime art style responds very well to Waifu2x upscaling. Check GBAtemp and LoversLab.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=hack+gu+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=hack+gu+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": ".hack//G.U.",
        "thumbnail_url": "",
        "tags": ["hack-gu", "bandai-namco", "jrpg", "anime", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "Waifu2x / ESRGAN (anime)",
    },
    {
        "id": "champions_norrath_textures",
        "name": "Champions of Norrath — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Champions of Norrath (SLUS-20734). "
            "Upscaled dungeon, character and spell effect textures."
        ),
        "context": "One of the best PS2 RPGs. HD textures make the detailed dungeons look even better. Check GBAtemp and Reddit r/ps2.",
        "author": "",
        "author_url": "https://www.reddit.com/r/ps2/search/?q=champions+norrath+texture",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.reddit.com/r/ps2/search/?q=champions+norrath+texture",
        "type": ModType.TEXTURE_PACK,
        "source": "Reddit",
        "game": "Champions of Norrath",
        "thumbnail_url": "",
        "tags": ["champions-norrath", "sony", "rpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "baldurs_gate_textures",
        "name": "Baldur's Gate: Dark Alliance — HD Textures",
        "description": (
            "Community HD texture replacements for Baldur's Gate: Dark Alliance (SLUS-20034). "
            "Upscaled dungeon, character and equipment textures for this classic action-RPG."
        ),
        "context": "Dark Alliance's top-down perspective makes HD textures very impactful. Check GBAtemp and PSX-Place for community packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=baldurs+gate+dark+alliance+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=baldurs+gate+dark+alliance+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Baldur's Gate: Dark Alliance",
        "thumbnail_url": "",
        "tags": ["baldurs-gate", "black-isle", "rpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ssx_textures",
        "name": "SSX Series — HD Texture Packs",
        "description": (
            "Community HD texture replacements for SSX (SLUS-20095), SSX Tricky (SLUS-20369) "
            "and SSX 3 (SLUS-20731). Upscaled mountain, character and trick effect textures."
        ),
        "context": "SSX's vibrant snowboarding tracks and colorful characters upscale beautifully. Check GBAtemp and GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=ssx+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=ssx+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "SSX series",
        "thumbnail_url": "",
        "tags": ["ssx", "ea", "sports", "snowboarding", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ff9_textures",
        "name": "Final Fantasy IX — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Final Fantasy IX (SLUS-01251 PS1/PS2). "
            "Upscaled character, world map and battle textures."
        ),
        "context": "FF9's unique painterly art style responds very well to ESRGAN anime upscaling. Check GBAtemp and PCSX2 forums.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=final+fantasy+ix+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=final+fantasy+ix+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Final Fantasy IX",
        "thumbnail_url": "",
        "tags": ["final-fantasy", "ff9", "square-enix", "jrpg", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN (anime model)",
    },
    {
        "id": "twisted_metal_textures",
        "name": "Twisted Metal: Black — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Twisted Metal: Black (SCUS-97038). "
            "Upscaled vehicle, arena and character textures for this iconic vehicular combat game."
        ),
        "context": "TM: Black's dark post-apocalyptic art style is dramatically enhanced by HD textures. Check GBAtemp and PSX-Place.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=twisted+metal+black+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=twisted+metal+black+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Twisted Metal: Black",
        "thumbnail_url": "",
        "tags": ["twisted-metal", "sony", "vehicular-combat", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "socom_textures",
        "name": "SOCOM: U.S. Navy SEALs — HD Texture Pack",
        "description": (
            "Community HD texture replacements for SOCOM: U.S. Navy SEALs (SCUS-97115). "
            "Upscaled environment, equipment and character textures."
        ),
        "context": "SOCOM's tactical environments upscale very well with ESRGAN. Check GBAtemp and PSX-Place for community packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=socom+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=socom+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "SOCOM: U.S. Navy SEALs",
        "thumbnail_url": "",
        "tags": ["socom", "sony", "tactical-shooter", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    {
        "id": "armored_core_textures",
        "name": "Armored Core Series — HD Texture Packs",
        "description": (
            "Community HD texture replacements for Armored Core 2 / 3 / Nexus on PS2. "
            "Upscaled mecha parts, arena and environment textures."
        ),
        "context": "Armored Core's detailed mech designs upscale well. Check GBAtemp and GameBanana for packs covering different AC titles.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=armored+core+texture+ps2&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=armored+core+texture+ps2&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Armored Core series",
        "thumbnail_url": "",
        "tags": ["armored-core", "fromsoftware", "mecha", "hd", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
    },
    # ── Additional PNACH Patches ──────────────────────────────────────────────
    {
        "id": "gow2_widescreen_pnach",
        "name": "God of War II — Widescreen + 60fps Patches",
        "description": (
            "Widescreen (16:9) and 60fps PNACH patches for God of War II (SCUS-97402). "
            "One of the most popular PS2 widescreen patches available."
        ),
        "context": "Fetch this patch from the PCSX2 GitHub using the 🔧 Fetch PNACH button. The 60fps patch dramatically improves the experience.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "God of War II",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "gow2", "god-of-war", "60fps", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "gta_vc_widescreen_pnach",
        "name": "GTA Vice City — Widescreen + 60fps Patch",
        "description": (
            "Widescreen (16:9) and 60fps PNACH patches for GTA Vice City (SLUS-20552). "
            "Corrects aspect ratio and enables smoother gameplay."
        ),
        "context": "Fetch from the PCSX2 GitHub using the 🔧 PNACH fetcher button and enter your game CRC.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "GTA Vice City",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "gta", "vice-city", "60fps", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "persona4_widescreen_pnach",
        "name": "Persona 4 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Persona 4 (SLUS-21782). "
            "Enables true 16:9 output for the beloved JRPG."
        ),
        "context": "Fetch from the PCSX2 GitHub using the 🔧 PNACH button. Pair with the HD texture pack for the best experience.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Persona 4",
        "thumbnail_url": "",
        "tags": ["widescreen", "persona", "persona4", "atlus", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "dmc3_widescreen_pnach",
        "name": "Devil May Cry 3 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Devil May Cry 3 (SLUS-21048). "
            "Removes black bars for a full widescreen experience."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches repo using the 🔧 PNACH button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Devil May Cry 3",
        "thumbnail_url": "",
        "tags": ["widescreen", "devil-may-cry", "dmc3", "capcom", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "tekken5_widescreen_pnach",
        "name": "Tekken 5 — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Tekken 5 (SLUS-21059). "
            "Enables native 16:9 output for the best-looking PS2 fighting game."
        ),
        "context": "Fetch from the PCSX2 GitHub using the 🔧 PNACH button. Tekken 5's high polygon count looks stunning in widescreen.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Tekken 5",
        "thumbnail_url": "",
        "tags": ["widescreen", "tekken5", "bandai-namco", "fighting", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "burnout3_widescreen_pnach",
        "name": "Burnout 3: Takedown — Widescreen Patch",
        "description": (
            "Widescreen (16:9) PNACH patch for Burnout 3: Takedown (SLUS-20872). "
            "Corrects the aspect ratio for proper 16:9 racing."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches repo. Burnout 3 at 60fps with widescreen is one of the best PS2 experiences.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Burnout 3: Takedown",
        "thumbnail_url": "",
        "tags": ["widescreen", "burnout3", "racing", "ea", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "gta_sa_widescreen_pnach",
        "name": "GTA San Andreas — Widescreen + 60fps Patches",
        "description": (
            "Widescreen (16:9) and 60fps PNACH patches for GTA San Andreas (SLUS-20946). "
            "Enables proper widescreen and smoother gameplay."
        ),
        "context": "Fetch from the PCSX2 GitHub. GTA SA is one of the most-requested widescreen patches and is well-maintained.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "GTA San Andreas",
        "thumbnail_url": "",
        "tags": ["widescreen", "gta", "san-andreas", "60fps", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "sly2_widescreen_pnach",
        "name": "Sly 2 & Sly 3 — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for Sly 2: Band of Thieves (SCUS-97316) "
            "and Sly 3: Honor Among Thieves (SCUS-97441)."
        ),
        "context": "Fetch these from the PCSX2 GitHub. The Sly series widescreen patches are well-maintained.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Sly 2 / Sly 3",
        "thumbnail_url": "",
        "tags": ["widescreen", "sly-cooper", "sony", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "crash_3_widescreen_pnach",
        "name": "Crash Bandicoot: The Huge Adventure / Crash Twinsanity — Patches",
        "description": (
            "Widescreen PNACH patches for Crash Twinsanity (SLUS-20903) and other "
            "Crash titles on PS2."
        ),
        "context": "Fetch from the PCSX2 GitHub widescreen patches using the 🔧 button.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Crash Twinsanity",
        "thumbnail_url": "",
        "tags": ["widescreen", "crash-bandicoot", "vivendi", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "dark_cloud_pnach",
        "name": "Dark Cloud / Dark Chronicle — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for Dark Cloud (SCUS-97111) and "
            "Dark Cloud 2 / Dark Chronicle (SCUS-97213)."
        ),
        "context": "Fetch from the PCSX2 GitHub. Dark Chronicle in widescreen is a dramatically improved experience.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Dark Cloud / Dark Chronicle",
        "thumbnail_url": "",
        "tags": ["widescreen", "dark-cloud", "level5", "rpg", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "katamari_widescreen_pnach",
        "name": "Katamari Damacy / We ♥ Katamari — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for Katamari Damacy (SLUS-20917) and "
            "We ♥ Katamari (SLUS-21181)."
        ),
        "context": "Fetch from the PCSX2 GitHub. Katamari's rolling action looks great in 16:9.",
        "author": "PCSX2 GitHub Contributors",
        "author_url": "https://github.com/PCSX2/pcsx2/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "source": "GitHub",
        "game": "Katamari Damacy",
        "thumbnail_url": "",
        "tags": ["widescreen", "katamari", "bandai-namco", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "dbz_bt3_60fps_pnach",
        "name": "Dragon Ball Z: Budokai Tenkaichi 3 — 60fps Patch",
        "description": (
            "60fps PNACH patch for DBZ Budokai Tenkaichi 3 (SLUS-21678). "
            "Unlocks the frame rate for drastically smoother battle gameplay."
        ),
        "context": "Community-made 60fps patch — look for it on GBAtemp and the PCSX2 forums. Pair with the widescreen patch for best results.",
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=budokai+tenkaichi&t=file_update",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/3519/?q=budokai+tenkaichi&t=file_update",
        "type": ModType.PNACH,
        "source": "GBAtemp",
        "game": "Dragon Ball Z: Budokai Tenkaichi 3",
        "thumbnail_url": "",
        "tags": ["60fps", "dbz", "dragon-ball", "fighting", "pnach"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Additional Cheat Sources ──────────────────────────────────────────────
    {
        "id": "pcsx2_cheatdb_github",
        "name": "PCSX2 Cheat Database — GitHub (All Games)",
        "description": (
            "The comprehensive PCSX2 community cheat database on GitHub. "
            "Contains hundreds of game cheat files in PNACH format covering widescreen, "
            "60fps, gameplay enhancements and more."
        ),
        "context": "Use the '🔧 Fetch PNACH from GitHub' button above to browse and install patches from this repository by CRC.",
        "author": "PCSX2 Community",
        "author_url": "https://github.com/PCSX2/cheatdb/graphs/contributors",
        "is_hub": False,
        "nsfw": False,
        "url": "https://github.com/PCSX2/cheatdb",
        "type": ModType.CHEAT,
        "source": "GitHub",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["cheats", "pnach", "official", "all-games", "community"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "gbatemp_cheat_database",
        "name": "GBAtemp — PS2 Cheat Code Database",
        "description": (
            "GBAtemp hosts an extensive PS2 cheat code collection including "
            "GameShark, CodeBreaker and PNACH format codes for hundreds of games."
        ),
        "context": "The best source for older cheat codes not found elsewhere. Author posts include game CRC and version info.",
        "author": "",
        "author_url": "https://gbatemp.net/search/3519/?q=ps2+cheat&t=file_update",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/3519/?q=ps2+cheat&t=file_update",
        "type": ModType.CHEAT,
        "source": "GBAtemp",
        "game": "",
        "thumbnail_url": "https://gbatemp.net/styles/gbatemp/logo.png",
        "tags": ["cheats", "codes", "community", "gbatemp"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    {
        "id": "psx_place_cheat_db",
        "name": "PSX-Place — PS2 Cheat Files Archive",
        "description": (
            "PSX-Place maintains a PS2 cheat file archive with PNACH codes, "
            "GameShark codes and game enhancement patches for PS2."
        ),
        "context": "PlayStation-focused community — authors include game CRC, region and version notes for every cheat upload.",
        "author": "",
        "author_url": "https://www.psx-place.com/resources/categories/ps2-cheats.19/",
        "is_hub": True,
        "nsfw": False,
        "url": "https://www.psx-place.com/resources/categories/ps2-cheats.19/",
        "type": ModType.CHEAT,
        "source": "PSX-Place",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "pnach", "psx-place", "community"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "",
    },
    # ── Additional Game-Specific Texture Pack Hubs ────────────────────────────
    {
        "id": "jak2_textures",
        "name": "Jak II — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Jak II (SCUS-97265 / SCES-52460). "
            "Search GBAtemp, GameBanana, and Reddit for upscaled packs."
        ),
        "context": "Search 'Jak II texture' on GBAtemp or GameBanana for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=jak+2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=jak+2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Jak II",
        "thumbnail_url": "",
        "tags": ["jak 2", "jak ii", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "jak3_textures",
        "name": "Jak 3 — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Jak 3 (SCUS-97330 / SCES-53203). "
            "Search GBAtemp, GameBanana, and Reddit for upscaled packs."
        ),
        "context": "Search 'Jak 3 texture' on GBAtemp or GameBanana for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=jak+3+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=jak+3+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Jak 3",
        "thumbnail_url": "",
        "tags": ["jak 3", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ratchet_clank_gac_textures",
        "name": "Ratchet & Clank: Going Commando — HD Textures",
        "description": (
            "Community HD texture replacements for Ratchet & Clank: Going Commando "
            "(SCUS-97268 / SCES-51607). Browse GBAtemp and GameBanana for packs."
        ),
        "context": "Search 'Ratchet Clank Going Commando texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=ratchet+clank+going+commando+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=ratchet+clank+going+commando+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Ratchet & Clank: Going Commando",
        "thumbnail_url": "",
        "tags": ["ratchet clank", "going commando", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ratchet_clank_uy_textures",
        "name": "Ratchet & Clank: Up Your Arsenal — HD Textures",
        "description": (
            "Community HD texture replacements for Ratchet & Clank: Up Your Arsenal "
            "(SCUS-97353 / SCES-52456). Browse GBAtemp and GameBanana for packs."
        ),
        "context": "Search 'Ratchet Clank Up Your Arsenal texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=ratchet+clank+up+your+arsenal+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=ratchet+clank+up+your+arsenal+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Ratchet & Clank: Up Your Arsenal",
        "thumbnail_url": "",
        "tags": ["ratchet clank", "up your arsenal", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "sly2_textures",
        "name": "Sly 2: Band of Thieves — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Sly 2: Band of Thieves "
            "(SCUS-97316 / SCES-52456). Search GBAtemp and GameBanana for packs."
        ),
        "context": "Search 'Sly 2 texture' on GBAtemp or GameBanana for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=sly+2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=sly+2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Sly 2: Band of Thieves",
        "thumbnail_url": "",
        "tags": ["sly 2", "sly cooper", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "sly3_textures",
        "name": "Sly 3: Honor Among Thieves — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Sly 3: Honor Among Thieves "
            "(SCUS-97421 / SCES-53350). Search GBAtemp and GameBanana for packs."
        ),
        "context": "Search 'Sly 3 texture' on GBAtemp or GameBanana for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=sly+3+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=sly+3+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Sly 3: Honor Among Thieves",
        "thumbnail_url": "",
        "tags": ["sly 3", "sly cooper", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "gran_turismo3_textures",
        "name": "Gran Turismo 3: A-Spec — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Gran Turismo 3: A-Spec "
            "(SCUS-97100 / SCES-50294). Search GBAtemp for upscaled track and car textures."
        ),
        "context": "Search 'Gran Turismo 3 texture' on GBAtemp or GameBanana for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=gran+turismo+3+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=gran+turismo+3+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Gran Turismo 3: A-Spec",
        "thumbnail_url": "",
        "tags": ["gran turismo 3", "gt3", "racing", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "burnout_revenge_textures",
        "name": "Burnout Revenge — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Burnout Revenge (SLUS-21349 / SLES-53662). "
            "Browse GBAtemp for upscaled car and track textures."
        ),
        "context": "Search 'Burnout Revenge texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=burnout+revenge+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=burnout+revenge+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Burnout Revenge",
        "thumbnail_url": "",
        "tags": ["burnout revenge", "burnout", "racing", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "prince_of_persia_sot_textures",
        "name": "Prince of Persia: Sands of Time — Community Pack Hub",
        "description": (
            "Community HD texture replacements for Prince of Persia: The Sands of Time "
            "(SLUS-20550 / SLES-51605). "
            "Browse GBAtemp and GameBanana for upscaled environment and character packs."
        ),
        "context": "Search 'Prince of Persia Sands of Time texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=prince+of+persia+sands+of+time+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=prince+of+persia+sands+of+time+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Prince of Persia: The Sands of Time",
        "thumbnail_url": "",
        "tags": ["prince of persia", "sands of time", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "prince_of_persia_ww_textures",
        "name": "Prince of Persia: Warrior Within — HD Textures",
        "description": (
            "Community HD texture replacements for Prince of Persia: Warrior Within "
            "(SLUS-21048 / SLES-52905). "
            "Browse GBAtemp and GameBanana for upscaled packs."
        ),
        "context": "Search 'Prince of Persia Warrior Within texture' on GBAtemp.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=prince+of+persia+warrior+within+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=prince+of+persia+warrior+within+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Prince of Persia: Warrior Within",
        "thumbnail_url": "",
        "tags": ["prince of persia", "warrior within", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "mortal_kombat_armageddon_textures",
        "name": "Mortal Kombat: Armageddon — HD Textures",
        "description": (
            "Community HD texture replacements for Mortal Kombat: Armageddon "
            "(SLUS-21444 / SLES-54735). "
            "Browse GBAtemp and GameBanana for fighter and stage texture packs."
        ),
        "context": "Search 'Mortal Kombat Armageddon texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=mortal+kombat+armageddon+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=mortal+kombat+armageddon+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Mortal Kombat: Armageddon",
        "thumbnail_url": "",
        "tags": ["mortal kombat", "armageddon", "fighting", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "castlevania_loi_textures",
        "name": "Castlevania: Lament of Innocence — HD Textures",
        "description": (
            "Community HD texture replacements for Castlevania: Lament of Innocence "
            "(SLUS-20845 / SLES-52157). "
            "Browse GBAtemp and PSX-Place for upscaled castle and character textures."
        ),
        "context": "Search 'Castlevania Lament Innocence texture' on GBAtemp or PSX-Place.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=castlevania+lament+of+innocence+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=castlevania+lament+of+innocence+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Castlevania: Lament of Innocence",
        "thumbnail_url": "",
        "tags": ["castlevania", "lament of innocence", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "fatal_frame2_textures",
        "name": "Fatal Frame II: Crimson Butterfly — HD Textures",
        "description": (
            "Community HD texture replacements for Fatal Frame II: Crimson Butterfly "
            "(SLUS-20811 / SLES-52384). "
            "Browse GBAtemp and PSX-Place for upscaled horror and environment textures."
        ),
        "context": "Search 'Fatal Frame 2 texture' on GBAtemp or PSX-Place for available packs.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=fatal+frame+2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=fatal+frame+2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Fatal Frame II: Crimson Butterfly",
        "thumbnail_url": "",
        "tags": ["fatal frame 2", "fatal frame", "horror", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "dmc2_textures",
        "name": "Devil May Cry 2 — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Devil May Cry 2 (SLUS-20783 / SLES-51390). "
            "Browse GBAtemp and GameBanana for upscaled environment and character packs."
        ),
        "context": "Search 'Devil May Cry 2 texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=devil+may+cry+2+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=devil+may+cry+2+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Devil May Cry 2",
        "thumbnail_url": "",
        "tags": ["devil may cry 2", "dmc2", "hd", "esrgan", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "ace_combat04_textures",
        "name": "Ace Combat 04: Shattered Skies — HD Textures",
        "description": (
            "Community HD texture replacements for Ace Combat 04: Shattered Skies "
            "(SLUS-20152 / SLES-50507). "
            "Browse GBAtemp and PSX-Place for upscaled aircraft and landscape textures."
        ),
        "context": "Search 'Ace Combat 04 texture' on GBAtemp or PSX-Place.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=ace+combat+04+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=ace+combat+04+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Ace Combat 04: Shattered Skies",
        "thumbnail_url": "",
        "tags": ["ace combat", "ace combat 04", "flight", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "timesplitters_fp_textures",
        "name": "TimeSplitters: Future Perfect — HD Textures",
        "description": (
            "Community HD texture replacements for TimeSplitters: Future Perfect "
            "(SLUS-21028 / SLES-53032). "
            "Browse GBAtemp and GameBanana for upscaled character and level textures."
        ),
        "context": "Search 'TimeSplitters Future Perfect texture' on GBAtemp or GameBanana.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=timesplitters+future+perfect+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=timesplitters+future+perfect+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "TimeSplitters: Future Perfect",
        "thumbnail_url": "",
        "tags": ["timesplitters", "future perfect", "fps", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "shadow_hearts2_textures",
        "name": "Shadow Hearts: Covenant — HD Texture Pack",
        "description": (
            "Community HD texture replacements for Shadow Hearts: Covenant "
            "(SLUS-20971 / SLES-52838). "
            "Browse GBAtemp and Reddit for upscaled JRPG character and world textures."
        ),
        "context": "Search 'Shadow Hearts Covenant texture' on GBAtemp or Reddit r/ps2.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=shadow+hearts+covenant+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=shadow+hearts+covenant+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Shadow Hearts: Covenant",
        "thumbnail_url": "",
        "tags": ["shadow hearts", "shadow hearts 2", "covenant", "jrpg", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "wild_arms5_textures",
        "name": "Wild Arms 5 — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Wild Arms 5 (SLUS-21742 / SLES-55134). "
            "Browse GBAtemp and Reddit for upscaled JRPG character and world textures."
        ),
        "context": "Search 'Wild Arms 5 texture' on GBAtemp or Reddit r/ps2.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=wild+arms+5+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=wild+arms+5+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Wild Arms 5",
        "thumbnail_url": "",
        "tags": ["wild arms 5", "wild arms", "jrpg", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "tales_of_the_abyss_textures",
        "name": "Tales of the Abyss — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Tales of the Abyss "
            "(SLUS-21386 / SLES-54438). "
            "Browse GBAtemp and Reddit for upscaled character, world, and battle textures."
        ),
        "context": "Search 'Tales of the Abyss texture' on GBAtemp or Reddit r/ps2.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=tales+of+the+abyss+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=tales+of+the+abyss+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Tales of the Abyss",
        "thumbnail_url": "",
        "tags": ["tales of the abyss", "tales", "jrpg", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    {
        "id": "suikoden5_textures",
        "name": "Suikoden V — HD Texture Pack (Community)",
        "description": (
            "Community HD texture replacements for Suikoden V (SLUS-21291 / SLES-53962). "
            "Browse GBAtemp and Reddit for upscaled JRPG character and environment textures."
        ),
        "context": "Search 'Suikoden 5 texture' on GBAtemp or Reddit r/ps2.",
        "author": "",
        "author_url": "https://gbatemp.net/search/?q=suikoden+5+texture&t=post",
        "is_hub": True,
        "nsfw": False,
        "url": "https://gbatemp.net/search/?q=suikoden+5+texture&t=post",
        "type": ModType.TEXTURE_PACK,
        "source": "GBAtemp",
        "game": "Suikoden V",
        "thumbnail_url": "",
        "tags": ["suikoden 5", "suikoden", "jrpg", "hd", "ps2"],
        "download_action": "",
        "upscale_tech": "ESRGAN / xBRZ",
    },
    # ── Additional PNACH Hubs ─────────────────────────────────────────────────
    {
        "id": "ps2wide_jak_pnach",
        "name": "Jak and Daxter Series — Widescreen Patches",
        "description": (
            "Widescreen and enhancement PNACH patches for the Jak and Daxter trilogy "
            "on PS2. Available on PS2Wide.net — covers Jak and Daxter, Jak II, and Jak 3."
        ),
        "context": "Search ps2wide.net for 'Jak' to find widescreen patches for all three games.",
        "author": "",
        "author_url": "https://ps2wide.net/pc.html",
        "is_hub": True,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Jak and Daxter",
        "thumbnail_url": "",
        "tags": ["jak", "jak and daxter", "widescreen", "pnach", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_crash_pnach",
        "name": "Crash Bandicoot Series — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for Crash Bandicoot PS2 titles on PS2Wide.net. "
            "Covers Wrath of Cortex, Twinsanity, and Crash of the Titans."
        ),
        "context": "Search ps2wide.net for 'Crash' to find widescreen patches.",
        "author": "",
        "author_url": "https://ps2wide.net/pc.html",
        "is_hub": True,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Crash Bandicoot series",
        "thumbnail_url": "",
        "tags": ["crash bandicoot", "widescreen", "pnach", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_ratchet_pnach",
        "name": "Ratchet & Clank Series — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for the Ratchet & Clank PS2 series on PS2Wide.net. "
            "Covers all four main PS2 entries in the series."
        ),
        "context": "Search ps2wide.net for 'Ratchet' to find widescreen patches for all games.",
        "author": "",
        "author_url": "https://ps2wide.net/pc.html",
        "is_hub": True,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Ratchet & Clank series",
        "thumbnail_url": "",
        "tags": ["ratchet clank", "widescreen", "pnach", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_sly_pnach",
        "name": "Sly Cooper Series — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for the Sly Cooper PS2 trilogy on PS2Wide.net. "
            "Covers Sly Cooper, Sly 2: Band of Thieves, and Sly 3: Honor Among Thieves."
        ),
        "context": "Search ps2wide.net for 'Sly' to find widescreen patches for all three games.",
        "author": "",
        "author_url": "https://ps2wide.net/pc.html",
        "is_hub": True,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Sly Cooper series",
        "thumbnail_url": "",
        "tags": ["sly cooper", "sly", "widescreen", "pnach", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    {
        "id": "ps2wide_silent_hill_pnach",
        "name": "Silent Hill Series — Widescreen Patches",
        "description": (
            "Widescreen PNACH patches for the Silent Hill PS2 series on PS2Wide.net. "
            "Covers Silent Hill 2, 3, 4: The Room, and Shattered Memories."
        ),
        "context": "Search ps2wide.net for 'Silent Hill' to find widescreen patches for all games.",
        "author": "",
        "author_url": "https://ps2wide.net/pc.html",
        "is_hub": True,
        "nsfw": False,
        "url": "https://ps2wide.net/pc.html",
        "type": ModType.PNACH,
        "source": "PS2Wide",
        "game": "Silent Hill series",
        "thumbnail_url": "",
        "tags": ["silent hill", "widescreen", "pnach", "horror", "ps2wide"],
        "download_action": "",
        "upscale_tech": "",
    },
    # ── Patreon Examples: paid / account-required / incomplete ────────────────
    {
        "id": "patreon_post_148478705",
        "name": "DeadOnTheInside — PS2 HD Texture Pack (WIP, Free Membership)",
        "description": (
            "HD texture replacement pack available to free Patreon members. "
            "This pack is currently a work-in-progress — not all textures are replaced yet. "
            "Log in to Patreon with a free account to access the attachment."
        ),
        "context": (
            "Download steps: 1) Create a free Patreon account. "
            "2) Follow DeadOnTheInside on Patreon (free). "
            "3) Open the post and download the attachment. "
            "4) Import in PS2 Mod Manager with the correct Game ID."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/148478705",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "hd", "wip", "free-membership", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": True,
        "requires_account": True,
        "is_complete": False,
    },
    {
        "id": "patreon_post_148718606",
        "name": "DeadOnTheInside — PS2 HD Texture Pack (Paid)",
        "description": (
            "Paid HD texture replacement pack available to Patreon subscribers. "
            "Requires an active paid Patreon membership to access and download."
        ),
        "context": (
            "Subscribe to the DeadOnTheInside Patreon at the appropriate tier "
            "to unlock this texture pack. Once downloaded, import using the "
            "Texture Packs panel and enter the Game ID shown in the post."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/148718606",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "",
        "thumbnail_url": "",
        "tags": ["patreon", "hd", "paid", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": False,
        "requires_account": True,
        "is_complete": True,
    },
    {
        "id": "patreon_post_148894264",
        "name": "Sims 2: Castaway — Sims Body Textures (Paid, Partial Coverage)",
        "description": (
            "Paid texture replacement pack for The Sims 2: Castaway (SLUS-21668) "
            "that replaces Sims character body textures only. "
            "This is a targeted partial pack — not a whole-game replacement. "
            "Requires a paid Patreon membership to access."
        ),
        "context": (
            "This pack is a body-texture swap, not an incomplete/WIP pack — it fully "
            "replaces what it targets. The game ID is SLUS-21668 (US). "
            "Download via Patreon, then import with Game ID SLUS-21668."
        ),
        "author": "DeadOnTheInside",
        "author_url": "https://www.patreon.com/c/DeadOnTheInside",
        "is_hub": False,
        "nsfw": False,
        "url": "https://www.patreon.com/posts/148894264",
        "type": ModType.TEXTURE_PACK,
        "source": "Patreon",
        "game": "The Sims 2: Castaway",
        "thumbnail_url": "",
        "tags": ["patreon", "sims", "castaway", "body-textures", "partial", "paid", "ps2"],
        "download_action": "",
        "direct_download_url": "",
        "upscale_tech": "ESRGAN",
        "is_free": False,
        "requires_account": True,
        "is_complete": False,
    },
]

# Collect unique sources for the source filter dropdown
ALL_SOURCES = sorted({e["source"] for e in CATALOGUE})

# ---------------------------------------------------------------------------
# Catalogue entry attribute helpers
# ---------------------------------------------------------------------------

#: Sources that always require creating an account (even a free one) to access
#: or download content from.
_ACCOUNT_REQUIRED_SOURCES: frozenset = frozenset({
    "GBAtemp",
    "LoversLab",
    "PSX-Place",
    "PCSX2 Forums",
    "Discord",
    "ScreenScraper",
    "Patreon",
})


def _entry_is_free(entry: dict) -> bool:
    """Return True if this entry's content is freely available (no payment needed).

    Defaults to True — only explicitly False for paid-subscription content."""
    return bool(entry.get("is_free", True))


def _entry_requires_account(entry: dict) -> bool:
    """Return True if accessing/downloading this entry requires an account.

    Checks explicit ``requires_account`` field first; falls back to inferring
    from the source (e.g. GBAtemp, LoversLab, Patreon always need accounts)."""
    if "requires_account" in entry:
        return bool(entry["requires_account"])
    return entry.get("source", "") in _ACCOUNT_REQUIRED_SOURCES


def _entry_is_complete(entry: dict) -> bool:
    """Return True if this is a full / complete pack (not a WIP or partial coverage).

    Defaults to True — only explicitly False for incomplete or partial-coverage packs."""
    return bool(entry.get("is_complete", True))

# ---------------------------------------------------------------------------
# Catalogue card widget
# ---------------------------------------------------------------------------

class CatalogueCard(QFrame):
    """A card in the mod browser showing one catalogue entry."""

    open_url = pyqtSignal(str)
    download_cover = pyqtSignal(dict)
    favorite_toggled = pyqtSignal(str, bool)   # author, is_favorite
    install_direct = pyqtSignal(dict)           # entry dict — in-app install requested

    def __init__(self, entry: dict, config: AppConfig, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.config = config
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setMaximumWidth(400)
        self._fav_btn = None   # set to a QLabel widget inside _build() for non-hub entries; hub entries skip the favourite button entirely, so callers must guard with `if self._fav_btn`
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

        # Status badges: 💰 Paid / 🔐 Account Required / 🔧 WIP or Partial
        if not _entry_is_free(self.entry):
            paid_lbl = QLabel("💰 Paid")
            paid_lbl.setStyleSheet(
                "background:#3d2000; color:#f0a000; border-radius:9px;"
                "padding: 2px 7px; font-size:10px;"
            )
            paid_lbl.setToolTip("This content requires a paid subscription to access.")
            header.addWidget(paid_lbl)
        if _entry_requires_account(self.entry):
            acct_lbl = QLabel("🔐 Account")
            acct_lbl.setStyleSheet(
                "background:#001a3d; color:#60a8e0; border-radius:9px;"
                "padding: 2px 7px; font-size:10px;"
            )
            acct_lbl.setToolTip(
                "Requires creating a free (or paid) account to access or download."
            )
            header.addWidget(acct_lbl)
        if not _entry_is_complete(self.entry):
            wip_lbl = QLabel("🔧 WIP/Partial")
            wip_lbl.setStyleSheet(
                "background:#1a1000; color:#d08040; border-radius:9px;"
                "padding: 2px 7px; font-size:10px;"
            )
            wip_lbl.setToolTip(
                "This pack is incomplete, a work-in-progress, or only covers "
                "part of the game (e.g. specific characters or areas)."
            )
            header.addWidget(wip_lbl)

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

        # Author row — distinguishes a specific named author from a community hub
        is_hub = self.entry.get("is_hub", False)
        author_row = QHBoxLayout()

        if is_hub:
            # Hub entry: multiple authors, no specific person to credit
            author_lbl = QLabel(
                f"🔍 Multiple authors — see source for individual uploaders"
            )
            author_lbl.setStyleSheet(
                "color: #507090; font-size: 10px; font-style: italic;"
            )
            author_row.addWidget(author_lbl, 1)
        else:
            # Specific person: show their name with profile link
            author_lbl = QLabel(f"👤 {self.entry['author']}")
            author_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
            author_row.addWidget(author_lbl)
            author_row.addStretch()

            # Favorite author button (only for known individuals)
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

            # Profile link button
            if self.entry.get("author_url"):
                author_link = QPushButton("🔗")
                author_link.setFixedSize(26, 22)
                author_link.setStyleSheet(
                    "border: none; background: transparent; font-size: 14px; color: #5080d0;"
                )
                author_link.setToolTip(
                    f"View {self.entry['author']}'s profile on {self.entry.get('source', 'source site')}"
                )
                author_link.clicked.connect(
                    lambda: self.open_url.emit(self.entry["author_url"])
                )
                author_row.addWidget(author_link)

        # For hub entries, still allow a "Browse source" link
        if is_hub and self.entry.get("author_url"):
            browse_link = QPushButton("🔍 Browse")
            browse_link.setFixedWidth(72)
            browse_link.setStyleSheet(
                "border: none; background: transparent; font-size: 10px;"
                "color: #507090; text-decoration: underline;"
            )
            browse_link.setToolTip(
                f"Browse all mods on {self.entry.get('source', 'this source')}"
            )
            browse_link.clicked.connect(
                lambda: self.open_url.emit(self.entry["author_url"])
            )
            author_row.addWidget(browse_link)

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

        # Button row: always show both Visit Source and Download buttons side by side
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        visit_btn = QPushButton("🌐 Visit Source")
        visit_btn.setObjectName("primary_btn")
        visit_btn.clicked.connect(lambda: self.open_url.emit(self.entry["url"]))
        action_row.addWidget(visit_btn, 1)

        # Download button is always shown — opens the download/install dialog
        # so users can paste a direct link for any entry in the catalogue.
        has_direct = bool(self.entry.get("direct_download_url"))
        dl_label = "⬇ Install In-App" if has_direct else "⬇ Download from URL"
        dl_btn = QPushButton(dl_label)
        dl_btn.setObjectName("primary_btn")
        dl_btn.setToolTip(
            "Download and install this mod directly in PS2 Mod Manager.\n"
            "Paste a direct download link (ZIP, 7z, PNACH, Google Drive…) "
            "to download and install a mod."
        )
        dl_btn.clicked.connect(lambda: self.install_direct.emit(self.entry))
        action_row.addWidget(dl_btn, 1)

        layout.addLayout(action_row)

        if self.entry.get("download_action") == "cover_by_id":
            cover_btn = QPushButton("🖼 Download Cover by ID")
            cover_btn.clicked.connect(lambda: self.download_cover.emit(self.entry))
            layout.addWidget(cover_btn)

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
            "Supported: HTTPS links to ZIP, 7z, PNACH, PNG, Google Drive, "
            "<span style='color:#60b0e0;'>MediaFire</span> (auto-resolved).<br>"
            "MEGA links must be downloaded manually.<br>"
            "<span style='color:#a08040;'>🔒 Patreon attachments:</span> "
            "log in to Patreon, open the post, download <b>all parts</b> to the same "
            "folder, then use <b>📦 Archive</b> import in the Texture Packs panel — "
            "select Part 1 and the app will find and extract all other parts automatically."
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
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Short description of the mod")
        self._source_url_edit = QLineEdit()
        self._source_url_edit.setPlaceholderText("Source page URL (e.g. https://gbatemp.net/threads/…)")

        for label, edit in [
            ("Name:", self._name_edit),
            ("Author:", self._author_edit),
            ("Game:", self._game_edit),
            ("Desc:", self._desc_edit),
            ("Source:", self._source_url_edit),
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
    def _convert_url(url: str) -> Optional[str]:
        """Convert a share-page URL to a direct download URL where possible.

        Handles:
        * Google Drive share links → direct ``uc?export=download`` URL
        * MediaFire file-page links → resolved via :func:`resolve_mediafire_url`

        Returns the converted URL, or the original *url* unchanged if no
        conversion was needed.  Returns ``None`` if a MediaFire page fetch was
        attempted but failed (so the caller can show an appropriate error).
        """
        import re as _re
        # Google Drive
        m = _re.search(r"drive\.google\.com/file/d/([^/?]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
        m2 = _re.search(r"drive\.google\.com/open[?]id=([^&]+)", url)
        if m2:
            return f"https://drive.google.com/uc?export=download&id={m2.group(1)}"

        # MediaFire file page — resolve to direct download URL
        try:
            import urllib.parse as _up
            _psd = _up.urlparse(url)
            _netloc = _psd.netloc.lower()
            _is_mf = (_netloc in ("www.mediafire.com", "mediafire.com")
                      and "/file/" in _psd.path.lower())
        except Exception:
            _is_mf = False
        if _is_mf:
            from src.core.downloader import resolve_mediafire_url
            resolved = resolve_mediafire_url(url)
            return resolved  # None if resolution failed

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
        try:
            import urllib.parse as _up
            _psd2 = _up.urlparse(raw_url)
            _nl2 = _psd2.netloc.lower()
            _is_mf_raw = (_nl2 in ("www.mediafire.com", "mediafire.com")
                          and "/file/" in _psd2.path.lower())
        except Exception:
            _is_mf_raw = False
        if _is_mf_raw:
            self._dl_btn.setEnabled(False)
            self._progress.show()
            self._status.setText("🔍 Resolving MediaFire link…")

            def _resolve_then_download():
                url = self._convert_url(raw_url)
                if not url:
                    def _mf_err():
                        self._status.setText(
                            "❌  Could not resolve MediaFire download link.\n"
                            "Please open the MediaFire page in your browser, click Download,\n"
                            "and paste the resulting direct URL here."
                        )
                        self._progress.hide()
                        self._dl_btn.setEnabled(True)
                    QTimer.singleShot(0, _mf_err)
                    return
                QTimer.singleShot(0, lambda: self._status.setText("Downloading…"))
                self._run_download(raw_url, url)

            threading.Thread(target=_resolve_then_download, daemon=True).start()
            return

        url = self._convert_url(raw_url)
        if url is None:
            url = raw_url
        mod_type = self._type_combo.currentData()
        storage = self.config.mods_storage_path
        if not storage:
            QMessageBox.warning(self, "Storage Not Configured",
                "Please configure a Mod Storage folder in Settings first.")
            return
        self._dl_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Downloading...")
        self._run_download(raw_url, url)

    def _run_download(self, raw_url: str, url: str):
        """Perform the actual file download + install on a background thread."""
        mod_type = self._type_combo.currentData()
        storage = self.config.mods_storage_path
        if not storage:
            def _no_storage():
                QMessageBox.warning(self, "Storage Not Configured",
                    "Please configure a Mod Storage folder in Settings first.")
                self._progress.hide()
                self._dl_btn.setEnabled(True)
            QTimer.singleShot(0, _no_storage)
            return

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
                description = self._desc_edit.text().strip()
                source_url = self._source_url_edit.text().strip() or raw_url
                mod = mgr.install_from_folder(
                    source_path=dest, mod_type=mod_type, dest_base=storage,
                    name=name, author=author, game_id=game,
                    description=description, source_url=source_url,
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

#: Maximum number of widescreen-patch rows displayed at once in PnachGitHubDialog.
#: The PCSX2 repo has 500+ patches; rendering them all at once degrades UI
#: performance, so we cap the list and rely on the CRC search to narrow results.
_MAX_PATCH_DISPLAY = 200


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

        for patch in patches[:_MAX_PATCH_DISPLAY]:
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


# ---------------------------------------------------------------------------
# GBAtemp thread scraper dialog
# ---------------------------------------------------------------------------

class GBATempScraperDialog(QDialog):
    """Paste a GBAtemp thread URL to auto-discover author info and download links.

    The dialog:
    1. Fetches and parses the GBAtemp thread page (via :func:`scrape_gbatemp_thread`)
    2. Shows the detected title, author, game serial, and every download link found
    3. Lets the user one-click-install any of the discovered variants
    """

    def __init__(self, config: AppConfig, db, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.setWindowTitle("🔍 Scrape GBAtemp Thread")
        self.setMinimumSize(720, 560)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        intro = QLabel(
            "<b>Paste a GBAtemp thread URL</b> to automatically discover the author, "
            "game serial, and all download links (MediaFire, Google Drive, MEGA, etc.).<br>"
            "Each discovered link is offered as a one-click install."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("GBAtemp URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://gbatemp.net/threads/<thread-name>.<id>/"
        )
        url_row.addWidget(self._url_edit, 1)
        self._scan_btn = QPushButton("🔍 Scan")
        self._scan_btn.setObjectName("primary_btn")
        self._scan_btn.clicked.connect(self._scan)
        url_row.addWidget(self._scan_btn)
        layout.addLayout(url_row)

        # Results area (hidden until a scan completes)
        self._results_frame = QFrame()
        self._results_frame.setObjectName("card")
        self._results_frame.hide()
        self._results_layout = QVBoxLayout(self._results_frame)
        self._results_layout.setContentsMargins(12, 10, 12, 10)
        self._results_layout.setSpacing(8)
        layout.addWidget(self._results_frame)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #9090b0;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

    # ------------------------------------------------------------------
    def _scan(self):
        url = self._url_edit.text().strip()
        if not url:
            self._status.setText("⚠  Please enter a GBAtemp thread URL")
            return
        if "gbatemp.net" not in url.lower():
            self._status.setText("⚠  URL does not appear to be a GBAtemp thread")
            return

        self._scan_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Fetching thread…")
        # Clear previous results
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._results_frame.hide()

        def _run():
            from src.core.downloader import scrape_gbatemp_thread
            data = scrape_gbatemp_thread(url)
            QTimer.singleShot(0, lambda: self._show_results(data))

        threading.Thread(target=_run, daemon=True).start()

    def _show_results(self, data: dict):
        self._progress.hide()
        self._scan_btn.setEnabled(True)

        if not data.get("title") and not data.get("download_urls"):
            self._status.setText(
                "❌  Could not parse the thread. "
                "Check that the URL is a public GBAtemp thread and try again."
            )
            return

        self._status.setText("")
        rl = self._results_layout

        # ── Meta row ────────────────────────────────────────────────────
        title_lbl = QLabel(f"<b>{data.get('title', '(unknown title)')}</b>")
        title_lbl.setTextFormat(Qt.TextFormat.RichText)
        title_lbl.setWordWrap(True)
        rl.addWidget(title_lbl)

        meta_row = QHBoxLayout()
        if data.get("author"):
            author_lbl = QLabel(f"👤 {data['author']}")
            author_lbl.setStyleSheet("color: #8080c0;")
            meta_row.addWidget(author_lbl)
        if data.get("game_serial"):
            serial_lbl = QLabel(f"🎮 {data['game_serial']}")
            serial_lbl.setStyleSheet("color: #80b0ff;")
            meta_row.addWidget(serial_lbl)
        meta_row.addStretch()
        rl.addLayout(meta_row)

        download_urls = data.get("download_urls", [])
        if not download_urls:
            rl.addWidget(QLabel("ℹ  No recognised download links found in this thread."))
            self._results_frame.show()
            return

        rl.addWidget(QLabel(f"Found <b>{len(download_urls)}</b> download link(s):"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(260)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        links_widget = QWidget()
        links_layout = QVBoxLayout(links_widget)
        links_layout.setSpacing(6)
        links_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(links_widget)
        rl.addWidget(scroll)

        for dl in download_urls:
            row_frame = QFrame()
            row_frame.setObjectName("card")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(8, 6, 8, 6)

            host_lbl = QLabel(f"[{dl['host']}]")
            host_lbl.setStyleSheet("color: #6090c0; font-size: 10px; min-width: 80px;")
            row_layout.addWidget(host_lbl)

            label_lbl = QLabel(dl["label"])
            label_lbl.setStyleSheet("color: #c0c0e0; font-size: 11px;")
            label_lbl.setWordWrap(True)
            row_layout.addWidget(label_lbl, 1)

            # Open button (browser)
            open_btn = QPushButton("🌐")
            open_btn.setFixedSize(28, 26)
            open_btn.setToolTip("Open in browser")
            open_btn.setStyleSheet("border: none; background: transparent; font-size: 14px;")
            dl_url = dl["url"]  # capture for lambda
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            open_btn.clicked.connect(
                lambda _checked, u=dl_url: QDesktopServices.openUrl(QUrl(u))
            )
            row_layout.addWidget(open_btn)

            # Install button
            install_btn = QPushButton("⬇ Install")
            install_btn.setObjectName("primary_btn")
            install_btn.setFixedWidth(80)
            install_btn.setToolTip("Download and install this mod in PS2 Mod Manager")
            author = data.get("author", "")
            serial = data.get("game_serial", "")
            title = data.get("title", "")
            source = data.get("source_url", "")
            install_btn.clicked.connect(
                lambda _checked, u=dl_url, a=author, s=serial, t=title, src=source:
                    self._install(u, a, s, t, src)
            )
            row_layout.addWidget(install_btn)

            links_layout.addWidget(row_frame)

        links_layout.addStretch()
        self._results_frame.show()

    def _install(self, url: str, author: str, serial: str, title: str, source_url: str):
        """Open the DownloadInstallDialog pre-filled from a scraped link."""
        dlg = DownloadInstallDialog(self.config, self.db, self)
        dlg._url_edit.setText(url)
        dlg._author_edit.setText(author)
        if serial:
            dlg._game_edit.setText(serial)
        if title:
            dlg._name_edit.setText(title)
        dlg._source_url_edit.setText(source_url)
        dlg.exec()


# ---------------------------------------------------------------------------
# Tab content widget
# ---------------------------------------------------------------------------

class _CatalogueTabContent(QWidget):
    favorite_toggled = pyqtSignal(str, bool)
    install_direct = pyqtSignal(dict)   # emitted when a card's Install button is clicked
    result_count_changed = pyqtSignal(int, int)  # (visible, total)

    def __init__(self, entries: list, config: AppConfig, parent=None):
        super().__init__(parent)
        self._all_entries = entries
        self.config = config
        self._current_query = ""
        self._current_source = ""
        self._current_author = ""
        self._show_favs_only = False
        self._show_nsfw = False
        self._show_paid = False
        self._show_account_required = True
        self._show_incomplete = True

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
        # Populate with NSFW and paid content hidden by default
        initial = [
            e for e in entries
            if not e.get("nsfw", False) and _entry_is_free(e)
        ]
        self._populate(initial)

    def apply_filters(self, query: str = "", source: str = "",
                      author: str = "", favs_only: bool = False,
                      show_nsfw: bool = False,
                      show_paid: bool = False,
                      show_account_required: bool = True,
                      show_incomplete: bool = True):
        self._current_query = query
        self._current_source = source
        self._current_author = author
        self._show_favs_only = favs_only
        self._show_nsfw = show_nsfw
        self._show_paid = show_paid
        self._show_account_required = show_account_required
        self._show_incomplete = show_incomplete

        q = query.lower()
        fav_authors = getattr(self.config, "favorite_authors", [])

        filtered = []
        for e in self._all_entries:
            # NSFW filter — hide adult-content entries unless the user enables them
            if e.get("nsfw", False) and not show_nsfw:
                continue
            # Paid filter — hide paid content unless the user opts in
            if not _entry_is_free(e) and not show_paid:
                continue
            # Account-required filter
            if _entry_requires_account(e) and not show_account_required:
                continue
            # Incomplete/partial filter
            if not _entry_is_complete(e) and not show_incomplete:
                continue
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
            card.install_direct.connect(self.install_direct.emit)
            self._cards_layout.addWidget(card, i // cols, i % cols)

        remainder = len(entries) % cols
        if remainder and entries:
            for j in range(cols - remainder):
                spacer = QWidget()
                spacer.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                self._cards_layout.addWidget(spacer, len(entries) // cols, remainder + j)

        self.result_count_changed.emit(len(entries), len(self._all_entries))

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

        gbatemp_btn = QPushButton("🔍 Scan GBAtemp Post")
        gbatemp_btn.setToolTip(
            "Paste a GBAtemp thread URL to auto-discover the author, game serial, "
            "and all download links for one-click in-app installation"
        )
        gbatemp_btn.clicked.connect(self._open_gbatemp_scraper)
        toolbar.addWidget(gbatemp_btn)

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

        # Author filter — only shows named (non-hub) authors with a real profile
        filter_row.addWidget(QLabel("👤 Author:"))
        self._author_filter = QComboBox()
        self._author_filter.setMinimumWidth(150)
        self._author_filter.addItem("All Authors", "")
        # Only include non-empty author values (hub entries have author="")
        named_authors = sorted({e["author"] for e in CATALOGUE if e.get("author")})
        for a in named_authors:
            fav = a in getattr(self.config, "favorite_authors", [])
            self._author_filter.addItem(("❤ " if fav else "") + a, a)
        self._author_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._author_filter)

        # Favorites only checkbox
        self._favs_check = QCheckBox("❤ Favorites Only")
        self._favs_check.setStyleSheet("color: #c08090; font-size: 12px;")
        self._favs_check.stateChanged.connect(self._apply_filters)
        filter_row.addWidget(self._favs_check)

        # NSFW toggle — hidden by default; LoversLab results etc. are NSFW-adjacent
        self._nsfw_check = QCheckBox("🔞 Show NSFW")
        self._nsfw_check.setChecked(getattr(self.config, "show_nsfw", False))
        self._nsfw_check.setStyleSheet("color: #c06060; font-size: 12px;")
        self._nsfw_check.setToolTip(
            "LoversLab and similar sources may contain adult content.\n"
            "Enable this to show those results in the browser."
        )
        self._nsfw_check.stateChanged.connect(self._on_nsfw_toggled)
        filter_row.addWidget(self._nsfw_check)

        filter_row.addStretch()
        content.addLayout(filter_row)

        # ── Content-type filter row ───────────────────────────────────────
        type_filter_row = QHBoxLayout()
        type_filter_row.setSpacing(8)

        # Paid content toggle
        self._paid_check = QCheckBox("💰 Show Paid")
        self._paid_check.setChecked(getattr(self.config, "show_paid", False))
        self._paid_check.setStyleSheet("color: #e0a040; font-size: 12px;")
        self._paid_check.setToolTip(
            "By default only free content is shown.\n"
            "Enable this to also see paid / subscription-only texture packs and mods."
        )
        self._paid_check.stateChanged.connect(self._on_paid_toggled)
        type_filter_row.addWidget(self._paid_check)

        # Account-required toggle
        self._acct_check = QCheckBox("🔐 Show Account-Required")
        self._acct_check.setChecked(getattr(self.config, "show_account_required", True))
        self._acct_check.setStyleSheet("color: #60a8e0; font-size: 12px;")
        self._acct_check.setToolTip(
            "Some sources (GBAtemp, LoversLab, Patreon, PCSX2 Forums, Discord) \n"
            "require a free or paid account to download files.\n"
            "Uncheck to hide those entries and only show account-free sources."
        )
        self._acct_check.stateChanged.connect(self._on_acct_toggled)
        type_filter_row.addWidget(self._acct_check)

        # Incomplete / partial packs toggle
        self._incomplete_check = QCheckBox("🔧 Show Incomplete/Partial")
        self._incomplete_check.setChecked(getattr(self.config, "show_incomplete", True))
        self._incomplete_check.setStyleSheet("color: #d08040; font-size: 12px;")
        self._incomplete_check.setToolTip(
            "Show work-in-progress (WIP) or partial-coverage texture packs.\n"
            "Partial packs only replace textures for specific characters, areas,\n"
            "or body types rather than covering the whole game.\n"
            "Uncheck to show only complete, whole-game texture packs."
        )
        self._incomplete_check.stateChanged.connect(self._on_incomplete_toggled)
        type_filter_row.addWidget(self._incomplete_check)

        type_filter_row.addStretch()

        # Clear Filters button — resets all filters to defaults
        clear_btn = QPushButton("✖ Clear Filters")
        clear_btn.setToolTip("Reset all search and filter controls to their defaults")
        clear_btn.setFixedWidth(110)
        clear_btn.clicked.connect(self._clear_filters)
        type_filter_row.addWidget(clear_btn)

        content.addLayout(type_filter_row)

        # ── Result count label ────────────────────────────────────────────
        self._result_count_lbl = QLabel("")
        self._result_count_lbl.setStyleSheet("color: #5060a0; font-size: 11px;")
        self._result_count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        content.addWidget(self._result_count_lbl)

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
            tab.install_direct.connect(self._install_catalogue_entry)
            tab.result_count_changed.connect(self._on_result_count_changed)
            self._tab_contents.append(tab)
            self._tabs.addTab(tab, label)

        self._tabs.currentChanged.connect(self._on_tab_changed)
        content.addWidget(self._tabs, 1)

    def _apply_filters(self):
        query = self._search.text()
        source = self._source_filter.currentData() or ""
        author = self._author_filter.currentData() or ""
        favs_only = self._favs_check.isChecked()
        show_nsfw = self._nsfw_check.isChecked()
        show_paid = self._paid_check.isChecked()
        show_account_required = self._acct_check.isChecked()
        show_incomplete = self._incomplete_check.isChecked()
        for tab in self._tab_contents:
            tab.apply_filters(
                query, source, author, favs_only, show_nsfw,
                show_paid, show_account_required, show_incomplete,
            )

    def _on_nsfw_toggled(self, state: int):
        """Persist the NSFW preference and re-apply filters."""
        show_nsfw = bool(state)
        self.config.show_nsfw = show_nsfw
        try:
            from src.core.config import save_config
            save_config(self.config)
        except Exception:
            pass
        self._apply_filters()

    def _on_paid_toggled(self, state: int):
        """Persist the show-paid preference and re-apply filters."""
        self.config.show_paid = bool(state)
        try:
            from src.core.config import save_config
            save_config(self.config)
        except Exception:
            pass
        self._apply_filters()

    def _on_acct_toggled(self, state: int):
        """Persist the show-account-required preference and re-apply filters."""
        self.config.show_account_required = bool(state)
        try:
            from src.core.config import save_config
            save_config(self.config)
        except Exception:
            pass
        self._apply_filters()

    def _on_incomplete_toggled(self, state: int):
        """Persist the show-incomplete preference and re-apply filters."""
        self.config.show_incomplete = bool(state)
        try:
            from src.core.config import save_config
            save_config(self.config)
        except Exception:
            pass
        self._apply_filters()

    def _on_result_count_changed(self, visible: int, total: int):
        """Update the result count label when the active tab's filter changes."""
        if visible == total:
            self._result_count_lbl.setText(f"Showing all {total} entries")
        else:
            self._result_count_lbl.setText(f"Showing {visible} of {total} entries")

    def _on_tab_changed(self, index: int):
        """Sync the result count label when the user switches tabs."""
        if 0 <= index < len(self._tab_contents):
            tab = self._tab_contents[index]
            # Ask the tab to re-emit its count by retrieving from its private state
            total = len(tab._all_entries)
            # Count visible by running the filter logic again (cheaply via signal)
            tab.apply_filters(
                self._search.text(),
                self._source_filter.currentData() or "",
                self._author_filter.currentData() or "",
                self._favs_check.isChecked(),
                self._nsfw_check.isChecked(),
                self._paid_check.isChecked(),
                self._acct_check.isChecked(),
                self._incomplete_check.isChecked(),
            )

    def _clear_filters(self):
        """Reset all search and filter controls to their default state."""
        # Block signals while resetting to avoid multiple filter refreshes
        for widget in (
            self._search,
            self._source_filter,
            self._author_filter,
            self._favs_check,
            self._nsfw_check,
            self._paid_check,
            self._acct_check,
            self._incomplete_check,
        ):
            widget.blockSignals(True)

        self._search.clear()
        self._source_filter.setCurrentIndex(0)
        self._author_filter.setCurrentIndex(0)
        self._favs_check.setChecked(False)
        self._nsfw_check.setChecked(getattr(self.config, "show_nsfw", False))
        self._paid_check.setChecked(False)
        self._acct_check.setChecked(True)
        self._incomplete_check.setChecked(True)

        for widget in (
            self._search,
            self._source_filter,
            self._author_filter,
            self._favs_check,
            self._nsfw_check,
            self._paid_check,
            self._acct_check,
            self._incomplete_check,
        ):
            widget.blockSignals(False)

        self._apply_filters()

    def _on_favorite_toggled(self, author: str, is_fav: bool):
        """Rebuild author dropdown when favorites change."""
        self._author_filter.blockSignals(True)
        current = self._author_filter.currentData() or ""
        self._author_filter.clear()
        self._author_filter.addItem("All Authors", "")
        # Only show named (non-hub) authors — hub entries have author=""
        named_authors = sorted({e["author"] for e in CATALOGUE if e.get("author")})
        for a in named_authors:
            fav = a in getattr(self.config, "favorite_authors", [])
            self._author_filter.addItem(("❤ " if fav else "") + a, a)
        idx = self._author_filter.findData(current)
        if idx >= 0:
            self._author_filter.setCurrentIndex(idx)
        self._author_filter.blockSignals(False)

    def _open_download_dialog(self):
        dlg = DownloadInstallDialog(self.config, self._db, self)
        dlg.exec()

    def _install_catalogue_entry(self, entry: dict):
        """Open the Download & Install dialog pre-filled from a catalogue entry."""
        dlg = DownloadInstallDialog(self.config, self._db, self)
        # Pre-fill from catalogue metadata
        dlg._url_edit.setText(entry.get("direct_download_url", ""))
        dlg._name_edit.setText(entry.get("name", ""))
        dlg._author_edit.setText(entry.get("author", ""))
        dlg._game_edit.setText(entry.get("game", ""))
        dlg._desc_edit.setText(entry.get("description", "")[:200])
        # source_url = the catalogue browse-page URL (where the user found this mod)
        dlg._source_url_edit.setText(entry.get("url", ""))
        # Set mod type combo
        mod_type = entry.get("type")
        if mod_type is not None:
            for i in range(dlg._type_combo.count()):
                if dlg._type_combo.itemData(i) == mod_type:
                    dlg._type_combo.setCurrentIndex(i)
                    break
        dlg.exec()

    def _open_pnach_github_dialog(self):
        dlg = PnachGitHubDialog(self.config, self._db, self)
        dlg.exec()

    def _open_gbatemp_scraper(self):
        dlg = GBATempScraperDialog(self.config, self._db, self)
        dlg.exec()

    def _open_url(self, url: str):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _reload_catalogue(self):
        """Clear all filters and reset the catalogue view."""
        self._clear_filters()
        self.emit_status("Catalogue reloaded")

    def refresh(self):
        self._apply_filters()
