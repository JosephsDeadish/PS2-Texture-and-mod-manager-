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
from src.core.downloader import DownloadError, download_file
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
# Tab content widget
# ---------------------------------------------------------------------------

class _CatalogueTabContent(QWidget):
    favorite_toggled = pyqtSignal(str, bool)

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

    def _open_url(self, url: str):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def refresh(self):
        self._apply_filters()
