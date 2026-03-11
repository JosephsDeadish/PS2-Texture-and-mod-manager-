"""Browse & Download panel — discover mods from public sources.

New in this version:
- Tabbed browsing per mod type (All / Textures / PNACH / Covers / Saves / Cheats)
- Live search across catalogue entries (name, game, author, tags)
- "Download from URL" dialog — paste any direct URL, the app downloads
  and auto-installs the mod with progress feedback
- Google Drive link conversion to direct download
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
)

from src.core.config_manager import THUMBNAILS_DIR
from src.core.downloader import DownloadError, download_file
from src.models.mod import AppConfig, ModType
from src.ui.base_panel import BasePanel


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

CATALOGUE: List[dict] = [
    # Texture Packs
    {
        "id": "pcsx2_wiki_textures",
        "name": "PCSX2 Texture Replacement Guide",
        "description": (
            "The official PCSX2 wiki explains how to create and install HD texture "
            "replacement packs. Browse community-made packs linked from the wiki."
        ),
        "url": "https://wiki.pcsx2.net/Texture_Replacement",
        "type": ModType.TEXTURE_PACK,
        "author": "PCSX2 Community",
        "game": "",
        "thumbnail_url": "https://wiki.pcsx2.net/images/pcsx2-icon.png",
        "tags": ["guide", "official"],
        "download_action": "",
    },
    {
        "id": "gbatemp_textures",
        "name": "GBAtemp PS2 Texture Packs",
        "description": (
            "GBAtemp.net hosts community-uploaded HD texture packs for PS2 games. "
            "Visit to browse and download individual packs."
        ),
        "url": "https://gbatemp.net/tags/ps2-texture-pack/",
        "type": ModType.TEXTURE_PACK,
        "author": "GBAtemp Community",
        "game": "",
        "thumbnail_url": "https://gbatemp.net/styles/gbatemp/logo.png",
        "tags": ["community", "hd"],
        "download_action": "",
    },
    {
        "id": "nexusmods_ps2",
        "name": "Nexus Mods — PS2 / PCSX2",
        "description": (
            "Nexus Mods PS2 / PCSX2 section. Community-contributed texture packs "
            "and mods. Browse and download freely."
        ),
        "url": "https://www.nexusmods.com/pcsx2",
        "type": ModType.TEXTURE_PACK,
        "author": "Nexus Mods",
        "game": "",
        "thumbnail_url": "https://www.nexusmods.com/favicon.ico",
        "tags": ["community", "textures", "hd"],
        "download_action": "",
    },
    {
        "id": "reddit_ps2_textures",
        "name": "r/ps2 — Mods & Textures",
        "description": (
            "Reddit r/ps2 community shares texture packs, mods, and patches. "
            "Search for your favourite game."
        ),
        "url": "https://www.reddit.com/r/ps2/search/?q=texture+pack&sort=new",
        "type": ModType.TEXTURE_PACK,
        "author": "Reddit r/ps2",
        "game": "",
        "thumbnail_url": "https://www.redditstatic.com/desktop2x/img/favicon/favicon-32x32.png",
        "tags": ["community", "hd", "reddit"],
        "download_action": "",
    },
    # PNACH
    {
        "id": "pcsx2_widescreen_github",
        "name": "PCSX2 Widescreen Patches (GitHub)",
        "description": (
            "Official collection of widescreen (16:9) PNACH patches for hundreds "
            "of PS2 games, maintained by the PCSX2 team."
        ),
        "url": "https://github.com/PCSX2/pcsx2/tree/master/bin/cheats_ws",
        "type": ModType.PNACH,
        "author": "PCSX2 Team",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["widescreen", "official", "open-source"],
        "download_action": "",
    },
    {
        "id": "pcsx2_cheats_forum",
        "name": "PCSX2 Cheat / PNACH Archive",
        "description": (
            "Community-maintained collection of PNACH cheat files for PS2 games, "
            "including widescreen hacks and 60fps patches."
        ),
        "url": "https://forums.pcsx2.net/Thread-PNACH-Patches",
        "type": ModType.PNACH,
        "author": "PCSX2 Forums",
        "game": "",
        "thumbnail_url": "https://pcsx2.net/favicon.ico",
        "tags": ["patches", "pnach", "widescreen", "60fps"],
        "download_action": "",
    },
    {
        "id": "ps2wide_patches",
        "name": "PS2Wide — Widescreen Hack DB",
        "description": (
            "Community database of widescreen and HD resolution hacks for "
            "hundreds of PS2 games in PNACH format."
        ),
        "url": "https://ps2wide.net",
        "type": ModType.PNACH,
        "author": "PS2Wide Community",
        "game": "",
        "thumbnail_url": "",
        "tags": ["widescreen", "resolution", "pnach"],
        "download_action": "",
    },
    {
        "id": "pcsx2_cheatdb",
        "name": "PCSX2 Cheat Database (GitHub)",
        "description": (
            "Community-maintained cheat archive for PCSX2 on GitHub. "
            "Contains WideScreen, 60FPS, and gameplay cheats in PNACH format."
        ),
        "url": "https://github.com/PCSX2/cheatdb",
        "type": ModType.CHEAT,
        "author": "PCSX2 Community",
        "game": "All Games",
        "thumbnail_url": "https://github.githubassets.com/favicons/favicon.png",
        "tags": ["cheats", "pnach", "official"],
        "download_action": "",
    },
    # Cover Art
    {
        "id": "gametdb_covers",
        "name": "GameTDB Cover Art (PS2)",
        "description": (
            "GameTDB.com provides free PS2 cover art by game serial/ID. "
            "Click Download Cover by ID to fetch art."
        ),
        "url": "https://www.gametdb.com/PS2",
        "type": ModType.COVER_ART,
        "author": "GameTDB",
        "game": "All Games",
        "thumbnail_url": "https://www.gametdb.com/favicon.ico",
        "tags": ["covers", "art", "official"],
        "download_action": "cover_by_id",
    },
    {
        "id": "launchbox_art",
        "name": "LaunchBox Games Database",
        "description": (
            "LaunchBox hosts an extensive database of PS2 game artwork including "
            "box fronts, backs, screenshots and more."
        ),
        "url": "https://gamesdb.launchbox-app.com/platforms/games/11",
        "type": ModType.COVER_ART,
        "author": "LaunchBox Community",
        "game": "",
        "thumbnail_url": "https://www.launchbox-app.com/favicon.ico",
        "tags": ["covers", "artwork", "community"],
        "download_action": "",
    },
    # Save Files
    {
        "id": "gamefaqs_saves",
        "name": "GameFAQs PS2 Save Files",
        "description": (
            "GameFAQs hosts community-submitted PS2 save files for hundreds of games. "
            "Download saves to pick up where someone left off."
        ),
        "url": "https://gamefaqs.gamespot.com/ps2/category/929-saves",
        "type": ModType.SAVE_FILE,
        "author": "GameFAQs Community",
        "game": "",
        "thumbnail_url": "https://gamefaqs.gamespot.com/favicon.ico",
        "tags": ["saves", "community"],
        "download_action": "",
    },
    {
        "id": "ps2saves_com",
        "name": "PS2 Saves Database",
        "description": (
            "Collection of PS2 save files shared by the community, organised by "
            "game title. Download and import with the Memory Card manager."
        ),
        "url": "https://ps2saves.com",
        "type": ModType.SAVE_FILE,
        "author": "PS2Saves Community",
        "game": "",
        "thumbnail_url": "",
        "tags": ["saves", "community"],
        "download_action": "",
    },
    # Cheats
    {
        "id": "codejunkies_ps2",
        "name": "Code Junkies PS2 Cheats",
        "description": (
            "Code Junkies maintains a database of PS2 cheat codes that can be "
            "converted to PNACH format for use with PCSX2."
        ),
        "url": "https://www.codejunkies.com/ps2/",
        "type": ModType.CHEAT,
        "author": "Code Junkies",
        "game": "",
        "thumbnail_url": "",
        "tags": ["cheats", "codes"],
        "download_action": "",
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
        self.setMinimumWidth(240)
        self.setMaximumWidth(380)
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
        header.addStretch()
        layout.addLayout(header)

        title = QLabel(self.entry["name"])
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        title.setWordWrap(True)
        layout.addWidget(title)

        if self.entry.get("game"):
            game_lbl = QLabel(f"🎮 {self.entry['game']}")
            game_lbl.setStyleSheet("color: #80b0ff; font-size: 11px;")
            layout.addWidget(game_lbl)

        author = QLabel(f"by {self.entry['author']}")
        author.setStyleSheet("color: #7070a0; font-size: 11px;")
        layout.addWidget(author)

        desc = QLabel(self.entry["description"])
        desc.setStyleSheet("color: #9090b0; font-size: 12px;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(72)
        layout.addWidget(desc)

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
    Google Drive share links are converted to direct-download URLs automatically.
    MEGA links are detected and the user is guided to download manually.
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
        self._game_edit.setPlaceholderText("Game name or serial ID")

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
        # Google Drive: /file/d/FILE_ID/
        m = re.search(r"drive\.google\.com/file/d/([^/?]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
        # Google Drive open link
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
            QMessageBox.warning(
                self, "Storage Not Configured",
                "Please configure a Mod Storage folder in Settings first.",
            )
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
                    source_path=dest,
                    mod_type=mod_type,
                    dest_base=storage,
                    name=name,
                    author=author,
                    game_id=game,
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
    def __init__(self, entries: list, config: AppConfig, parent=None):
        super().__init__(parent)
        self._all_entries = entries
        self.config = config
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

    def filter(self, query: str):
        q = query.lower()
        filtered = [
            e for e in self._all_entries
            if not q
            or q in e.get("name", "").lower()
            or q in e.get("description", "").lower()
            or q in e.get("author", "").lower()
            or q in e.get("game", "").lower()
            or any(q in t.lower() for t in e.get("tags", []))
        ]
        self._populate(filtered)

    def _populate(self, entries: list):
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

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search by name, game, author, tag…")
        self._search.setObjectName("search_bar")
        self._search.textChanged.connect(self._on_search)
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
            self._tab_contents.append(tab)
            self._tabs.addTab(tab, label)

        content.addWidget(self._tabs, 1)

    def _on_search(self, query: str):
        for tab in self._tab_contents:
            tab.filter(query)

    def _open_download_dialog(self):
        dlg = DownloadInstallDialog(self.config, self._db, self)
        dlg.exec()

    def refresh(self):
        for tab in self._tab_contents:
            tab.filter(self._search.text())
