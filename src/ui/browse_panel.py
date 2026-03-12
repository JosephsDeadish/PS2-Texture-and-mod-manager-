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
    QListWidget,
    QListWidgetItem,
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

from src.core.catalogue_loader import CATALOGUE, ALL_SOURCES
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
        # Outer layout: cover art on the left, all existing content on the right
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        # ── Left: cover art / game image panel ──────────────────────────────
        # Shown for entries with a game_serial or explicit thumbnail_url.
        # Size matches typical PS2 cover aspect ratio (2:3 → 60 × 88).
        self._cover_lbl = QLabel()
        self._cover_lbl.setFixedSize(60, 88)
        self._cover_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._cover_lbl.setStyleSheet(
            "background: #0a0f20; border: 1px solid #1a2050; border-radius: 4px;"
        )

        type_icons = {
            ModType.TEXTURE_PACK: "🎨",
            ModType.PNACH: "🔧",
            ModType.COVER_ART: "🖼️",
            ModType.SAVE_FILE: "💾",
            ModType.CHEAT: "⚡",
        }
        icon = type_icons.get(self.entry["type"], "📦")
        self._cover_lbl.setText(icon)
        self._cover_lbl.setStyleSheet(
            "background: #0a0f20; border: 1px solid #1a2050; border-radius: 4px;"
            "font-size: 28px;"
        )

        outer.addWidget(self._cover_lbl, 0, Qt.AlignmentFlag.AlignTop)

        # Kick off image loading (GameTDB from serial, then thumbnail_url fallback)
        self._thumb_lbl = self._cover_lbl  # alias — _load_thumbnail updates this
        serial = self.entry.get("game_serial", "")
        thumbnail_url = self.entry.get("thumbnail_url", "")
        if serial:
            # Try GameTDB cover art first; if that fails, fall back to thumbnail_url
            from src.core.downloader import gametdb_cover_url as _gcu
            cover_url = _gcu(serial)
            threading.Thread(
                target=self._load_cover_with_fallback,
                args=(cover_url, thumbnail_url),
                daemon=True,
            ).start()
        elif thumbnail_url:
            threading.Thread(
                target=self._load_thumbnail,
                args=(thumbnail_url,),
                daemon=True,
            ).start()

        # ── Right: all existing card content ────────────────────────────────
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        outer.addLayout(layout, 1)

        # Header row: type badge + source badge + status badges
        header = QHBoxLayout()

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

        # Game badge — shows game name AND serial (e.g. "🎮 God of War  ·  SCUS-97399")
        if self.entry.get("game"):
            serial_part = (
                f"  ·  <span style='color:#506080;'>{serial}</span>"
                if serial else ""
            )
            game_lbl = QLabel(
                f"<span style='color:#80b0ff;'>🎮 {self.entry['game']}</span>"
                + serial_part
            )
            game_lbl.setStyleSheet("font-size: 11px;")
            game_lbl.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(game_lbl)
        elif serial:
            # No game name field, but we have a serial — show the serial alone
            serial_lbl = QLabel(
                f"<span style='color:#506080; font-size:10px;'>{serial}</span>"
            )
            serial_lbl.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(serial_lbl)

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

    def _load_cover_with_fallback(self, primary_url: str, fallback_url: str):
        """Try *primary_url* (GameTDB cover); if it yields a null/empty image try *fallback_url*."""
        success = self._fetch_and_display(primary_url)
        if not success and fallback_url:
            self._fetch_and_display(fallback_url)

    def _load_thumbnail(self, url: str):
        """Load an image from *url* and display it in the cover art label."""
        self._fetch_and_display(url)

    def _fetch_and_display(self, url: str) -> bool:
        """Download *url* to a temp file, scale it to the cover art label size,
        and update the label on the main thread.  Returns True on success."""
        if not url:
            return False
        try:
            import urllib.request
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                tmp = f.name
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = resp.read()
            if len(data) < 512:
                # Too small — likely a 404 placeholder or empty response
                return False
            with open(tmp, "wb") as f:
                f.write(data)

            loaded = [False]

            def _update():
                if not self._cover_lbl:
                    return
                pix = QPixmap(tmp).scaled(
                    60, 88,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if not pix.isNull():
                    self._cover_lbl.setPixmap(pix)
                    self._cover_lbl.setText("")
                    self._cover_lbl.setStyleSheet(
                        "background: #0a0f20; border: 1px solid #1a2050; border-radius: 4px;"
                    )
                    loaded[0] = True
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

            QTimer.singleShot(0, _update)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Cover art download dialog
# ---------------------------------------------------------------------------

class CoverDownloadDialog(QDialog):
    """Download PS2 cover art from GameTDB by game serial or game title.

    The dialog has two input modes:
    * **Search by game name** — type part of a game title and click a matching
      suggestion to auto-fill the serial field.
    * **Enter serial directly** — type (or paste) the SCUS/SLUS/SLES serial
      and download immediately.
    """

    def __init__(self, config: AppConfig, parent=None, initial_serial: str = ""):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Download Cover Art")
        self.setMinimumWidth(520)
        self._build()
        if initial_serial:
            self._id_edit.setText(initial_serial)

    def _build(self):
        from src.core.game_registry import title_to_serials

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        hdr = QLabel(
            "Download PS2 cover art from "
            "<a href='https://www.gametdb.com'>GameTDB</a> — free, high-quality scans."
        )
        hdr.setOpenExternalLinks(True)
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        # ── Game Name Search ──────────────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        layout.addWidget(QLabel(
            "<b>Step 1 (optional):</b> Search by game name to find its serial:"
        ))
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("e.g. God of War, Persona 4, Crash Bandicoot…")
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_edit, 1)
        layout.addLayout(search_row)

        # Results list — hidden until there are suggestions
        self._suggestions = QListWidget()
        self._suggestions.setMaximumHeight(130)
        self._suggestions.hide()
        self._suggestions.itemClicked.connect(self._on_suggestion_clicked)
        layout.addWidget(self._suggestions)

        # ── Serial / ID field ─────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        layout.addWidget(QLabel(
            "<b>Step 2:</b> Enter (or confirm) the game serial and click Download:"
        ))
        id_row = QHBoxLayout()
        id_row.addWidget(QLabel("Serial:"))
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

        # Status + progress
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Buttons
        btns = QHBoxLayout()
        self._dl_btn = QPushButton("⬇ Download Cover")
        self._dl_btn.setObjectName("primary_btn")
        self._dl_btn.clicked.connect(self._download)
        btns.addWidget(self._dl_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        # Keep reference so the inner lambda can call it
        self._title_to_serials = title_to_serials

    # ------------------------------------------------------------------
    # Game-name search helpers
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str):
        """Populate the suggestions list from the game registry."""
        self._suggestions.clear()
        text = text.strip()
        if len(text) < 2:
            self._suggestions.hide()
            return
        hits = self._title_to_serials(text)
        if not hits:
            self._suggestions.hide()
            return
        for serial, title in hits[:20]:
            item = QListWidgetItem(f"{serial}  —  {title}")
            item.setData(Qt.ItemDataRole.UserRole, serial)
            self._suggestions.addItem(item)
        self._suggestions.show()

    def _on_suggestion_clicked(self, item: "QListWidgetItem"):
        """Fill the serial field when the user clicks a suggestion."""
        serial = item.data(Qt.ItemDataRole.UserRole)
        if serial:
            self._id_edit.setText(serial)
            self._suggestions.hide()
            self._status.setText(
                f"Serial set to <b>{serial}</b> — click Download to fetch cover art."
            )
            self._status.setTextFormat(Qt.TextFormat.RichText)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _download(self):
        from src.core.downloader import fetch_gametdb_art
        game_id = self._id_edit.text().strip()
        if not game_id:
            self._status.setText("⚠  Please enter a Game ID or search by name above")
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
            "Supported: HTTPS links to ZIP, 7z, RAR, PNACH, PNG, Google Drive, "
            "<span style='color:#60b0e0;'>MediaFire</span> (auto-resolved).<br>"
            "<span style='color:#a0c070;'>RAR files</span> are extracted automatically "
            "if the <code>rarfile</code> package and <code>unrar</code> tool are installed "
            "(run: <code>pip install rarfile</code>).<br>"
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
    """Paste a GBAtemp or PS2-Home post URL to auto-discover author info and download links.

    The dialog:
    1. Detects whether the URL is a GBAtemp page (threads or downloads) or a PS2-Home forum topic
    2. Fetches and parses the page via the appropriate scraper
    3. Shows the detected title, author, game serial, and every download link found
    4. Lets the user one-click-install any of the discovered variants
    """

    def __init__(self, config: AppConfig, db, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.setWindowTitle("🔍 Scan GBAtemp / PS2-Home Post")
        self.setMinimumSize(720, 560)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        intro = QLabel(
            "<b>Paste a GBAtemp or PS2-Home URL</b> to automatically discover the author, "
            "game serial, and all download links (MediaFire, Google Drive, MEGA, etc.).<br>"
            "Supported: GBAtemp threads, GBAtemp Downloads pages, and PS2-Home forum topics."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://gbatemp.net/threads/…  or  https://gbatemp.net/download/…  or  https://www.ps2-home.com/forum/viewtopic.php?…"
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

    @staticmethod
    def _classify_url(url: str) -> str:
        """Return 'gbatemp', 'ps2home', or '' for unrecognised URLs.

        Uses ``urllib.parse`` for domain validation to prevent substring-match
        bypasses (e.g. ``evil.com/gbatemp.net``).
        """
        import urllib.parse as _up
        try:
            netloc = _up.urlparse(url).netloc.lower()
        except Exception:
            return ""
        # Match exact domain or subdomain (e.g. www.gbatemp.net)
        if netloc == "gbatemp.net" or netloc.endswith(".gbatemp.net"):
            return "gbatemp"
        if netloc == "ps2-home.com" or netloc.endswith(".ps2-home.com"):
            return "ps2home"
        return ""

    # ------------------------------------------------------------------
    def _scan(self):
        url = self._url_edit.text().strip()
        if not url:
            self._status.setText("⚠  Please enter a GBAtemp or PS2-Home URL")
            return
        kind = self._classify_url(url)
        if not kind:
            self._status.setText(
                "⚠  URL does not appear to be a GBAtemp or PS2-Home page.\n"
                "Supported: gbatemp.net/threads/…, gbatemp.net/download/…, "
                "ps2-home.com/forum/viewtopic.php?…"
            )
            return

        self._scan_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Fetching page…")
        # Clear previous results
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._results_frame.hide()

        def _run():
            if kind == "gbatemp":
                from src.core.downloader import scrape_gbatemp_thread
                data = scrape_gbatemp_thread(url)
            else:
                from src.core.downloader import scrape_ps2home_post
                data = scrape_ps2home_post(url)
            QTimer.singleShot(0, lambda: self._show_results(data, kind))

        threading.Thread(target=_run, daemon=True).start()

    def _show_results(self, data: dict, kind: str):
        self._progress.hide()
        self._scan_btn.setEnabled(True)

        if not data.get("title") and not data.get("download_urls"):
            site = "GBAtemp" if kind == "gbatemp" else "PS2-Home"
            self._status.setText(
                f"❌  Could not parse the {site} post. "
                "Check that the URL is a public page and try again."
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
            rl.addWidget(QLabel("ℹ  No recognised download links found in this post."))
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

    def _download_cover(self, entry: dict):
        # Pre-fill the serial from the catalogue entry if available
        initial_serial = entry.get("game_serial", "")
        dlg = CoverDownloadDialog(self.config, self, initial_serial=initial_serial)
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

        gbatemp_btn = QPushButton("🔍 Scan GBAtemp/PS2-Home Post")
        gbatemp_btn.setToolTip(
            "Paste a GBAtemp thread, GBAtemp Downloads page, or PS2-Home forum topic URL "
            "to auto-discover the author, game serial, and all download links "
            "for one-click in-app installation"
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
        """Reload catalogue from disk, refresh filters and cards.

        Because the catalogue now lives in JSON files (``data/catalogue/``),
        calling this picks up any entries that were added since the app started
        without needing a full restart.
        """
        import importlib
        import src.core.catalogue_loader as _cl

        # Reload the module from disk so freshly-added JSON entries are picked up
        # even if Python has already cached the old catalogue in memory.
        importlib.reload(_cl)
        new_entries = _cl.CATALOGUE

        # Sync the module-level lists so all other references in this module
        # see the updated data without needing to re-import.
        _cl.CATALOGUE[:] = new_entries
        _cl.ALL_SOURCES[:] = sorted({e["source"] for e in new_entries})

        # Rebuild source filter options
        self._source_filter.clear()
        self._source_filter.addItem("All Sources", "")
        for src in _cl.ALL_SOURCES:
            self._source_filter.addItem(src, src)

        self._clear_filters()
        self.emit_status(f"Catalogue reloaded — {len(new_entries)} entries")

    def refresh(self):
        self._apply_filters()
