"""Browse & Download panel — discover mods from public sources."""

import os
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QDialog,
    QDialogButtonBox,
    QProgressBar,
    QFileDialog,
    QSizePolicy,
)

from src.core.config_manager import THUMBNAILS_DIR
from src.core.downloader import AsyncDownloader, DownloadError, download_file
from src.models.mod import AppConfig, ModType
from src.ui.base_panel import BasePanel
from src.ui.widgets import DownloadProgressWidget


# ---------------------------------------------------------------------------
# Catalogue entries (public, legal mod sources)
# ---------------------------------------------------------------------------

CATALOGUE = [
    {
        "id": "pcsx2_wiki_textures",
        "name": "PCSX2 Texture Replacement Guide",
        "description": (
            "The official PCSX2 wiki explains how to create and install HD texture "
            "replacement packs. Browse community-made texture packs linked from the wiki."
        ),
        "url": "https://wiki.pcsx2.net/Texture_Replacement",
        "type": ModType.TEXTURE_PACK,
        "author": "PCSX2 Community",
        "thumbnail_url": "",
        "tags": ["guide", "official"],
    },
    {
        "id": "gbatemp_textures",
        "name": "GBAtemp PS2 Texture Packs",
        "description": (
            "GBAtemp.net hosts community-uploaded HD texture packs for PS2 games. "
            "Visit the link to browse and download individual packs."
        ),
        "url": "https://gbatemp.net/tags/ps2-texture-pack/",
        "type": ModType.TEXTURE_PACK,
        "author": "GBAtemp Community",
        "thumbnail_url": "",
        "tags": ["community", "hd"],
    },
    {
        "id": "pcsx2_cheats",
        "name": "PCSX2 Cheat/PNACH Archive",
        "description": (
            "Community-maintained collection of PNACH cheat files for PS2 games. "
            "Includes widescreen hacks, 60fps patches, and more."
        ),
        "url": "https://forums.pcsx2.net/Thread-PNACH-Patches",
        "type": ModType.PNACH,
        "author": "PCSX2 Forums",
        "thumbnail_url": "",
        "tags": ["patches", "pnach", "widescreen"],
    },
    {
        "id": "pcsx2_widescreen",
        "name": "PS2 Widescreen Patches (GitHub)",
        "description": (
            "Open-source collection of widescreen patches for PS2 games, "
            "maintained on GitHub."
        ),
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "author": "PCSX2 Team",
        "thumbnail_url": "",
        "tags": ["widescreen", "official", "open-source"],
    },
    {
        "id": "gametdb_covers",
        "name": "GameTDB Cover Art (PS2)",
        "description": (
            "GameTDB.com provides free cover art images for PS2 games by game ID. "
            "Enter your game's serial/ID below to download its cover art."
        ),
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "author": "GameTDB",
        "thumbnail_url": "",
        "tags": ["covers", "art", "official"],
    },
    {
        "id": "reddit_ps2_mods",
        "name": "r/PS2 Mods Community",
        "description": (
            "The Reddit community for PS2 mods, patches and texture packs. "
            "A great place to discover and share mods."
        ),
        "url": "https://reddit.com/r/ps2",
        "type": ModType.TEXTURE_PACK,
        "author": "Reddit Community",
        "thumbnail_url": "",
        "tags": ["community"],
    },
]


# ---------------------------------------------------------------------------
# Catalogue card widget
# ---------------------------------------------------------------------------

class CatalogueCard(QFrame):
    """A card in the mod browser showing one catalogue entry."""

    open_url = pyqtSignal(str)
    download_cover = pyqtSignal(dict)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("card")
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Icon row
        type_icons = {
            ModType.TEXTURE_PACK: "🎨",
            ModType.PNACH: "🔧",
            ModType.COVER_ART: "🖼️",
            ModType.SAVE_FILE: "💾",
            ModType.CHEAT: "⚡",
        }
        icon = type_icons.get(self.entry["type"], "📦")

        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 28px;")
        header.addWidget(icon_lbl)

        type_lbl = QLabel(self.entry["type"].value.replace("_", " ").title())
        type_lbl.setObjectName("badge")
        type_lbl.setStyleSheet(
            "background:#0f3460; color:#80b0ff; border-radius:9px;"
            "padding: 2px 8px; font-size:11px;"
        )
        header.addWidget(type_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Title
        title = QLabel(self.entry["name"])
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Author
        author = QLabel(f"by {self.entry['author']}")
        author.setStyleSheet("color: #7070a0; font-size: 11px;")
        layout.addWidget(author)

        # Description
        desc = QLabel(self.entry["description"])
        desc.setStyleSheet("color: #9090b0; font-size: 12px;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(80)
        layout.addWidget(desc)

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

        # Buttons
        visit_btn = QPushButton("🌐 Visit Source")
        visit_btn.setObjectName("primary_btn")
        visit_btn.clicked.connect(lambda: self.open_url.emit(self.entry["url"]))
        layout.addWidget(visit_btn)

        if self.entry["type"] == ModType.COVER_ART:
            dl_btn = QPushButton("🖼 Download Cover by ID")
            dl_btn.clicked.connect(lambda: self.download_cover.emit(self.entry))
            layout.addWidget(dl_btn)


# ---------------------------------------------------------------------------
# Cover art download dialog
# ---------------------------------------------------------------------------

class CoverDownloadDialog(QDialog):
    """Dialog for downloading cover art from GameTDB by game ID."""

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
        self._status.setText(f"Downloading cover for {game_id}…")

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
# Browse panel
# ---------------------------------------------------------------------------

class BrowsePanel(BasePanel):
    """Panel for discovering and downloading mods from public sources."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("🌐  Browse & Download", "Discover community mods and resources", parent=parent)
        self.config = config
        self._build()

    def _build(self):
        content = self._content_layout

        # ---- Filter row ----
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search resources…")
        self._search.setObjectName("search_bar")
        self._search.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search, 1)

        self._type_filter = QComboBox()
        self._type_filter.addItem("All Types", None)
        self._type_filter.addItem("🎨 Texture Packs", ModType.TEXTURE_PACK)
        self._type_filter.addItem("🔧 PNACH Patches", ModType.PNACH)
        self._type_filter.addItem("🖼️ Cover Art", ModType.COVER_ART)
        self._type_filter.addItem("💾 Saves", ModType.SAVE_FILE)
        self._type_filter.addItem("⚡ Cheats", ModType.CHEAT)
        self._type_filter.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._type_filter)

        content.addLayout(filter_row)

        note = QLabel(
            "ℹ  These are links to community-maintained public resources. "
            "PS2 Mod Manager does not host or distribute any game content."
        )
        note.setStyleSheet(
            "background: #0f1830; color: #7070a0; font-size: 12px;"
            "border-radius: 6px; padding: 8px 12px;"
        )
        note.setWordWrap(True)
        content.addWidget(note)

        # ---- Grid of cards ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_container = QWidget()
        self._cards_layout = QGridLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 8, 0, 8)
        self._cards_layout.setSpacing(14)
        self._scroll.setWidget(self._cards_container)
        content.addWidget(self._scroll, 1)

        self._apply_filter()

    def _apply_filter(self):
        query = self._search.text().lower()
        type_filter = self._type_filter.currentData()

        entries = [
            e for e in CATALOGUE
            if (not query or query in e["name"].lower() or query in e["description"].lower())
            and (type_filter is None or e["type"] == type_filter)
        ]

        # Clear grid
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = 3
        for i, entry in enumerate(entries):
            card = CatalogueCard(entry)
            card.open_url.connect(self._open_url)
            card.download_cover.connect(self._download_cover)
            self._cards_layout.addWidget(card, i // cols, i % cols)

        # Fill remaining cells
        remainder = len(entries) % cols
        if remainder:
            for j in range(cols - remainder):
                spacer = QWidget()
                spacer.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                self._cards_layout.addWidget(
                    spacer, len(entries) // cols, remainder + j
                )

    def _open_url(self, url: str):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _download_cover(self, entry: dict):
        dlg = CoverDownloadDialog(self.config, self)
        dlg.exec()
