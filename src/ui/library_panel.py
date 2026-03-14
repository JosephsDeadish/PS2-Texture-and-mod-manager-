"""My Library panel — per-game view of installed mods.

Scans the user's game library folder (set in Settings → Game Library Path),
displays each discovered PS2 disc image as a clickable game card, and lets
the user enable / disable individual mods that target that game.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.game_library import GameEntry, scan_library
from src.core.mod_manager import ModDatabase, ModManager
from src.models.mod import AppConfig, ModInfo, ModType
from src.ui.base_panel import BasePanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_ICONS = {
    ModType.TEXTURE_PACK: "🎨",
    ModType.PNACH: "🔧",
    ModType.COVER_ART: "🖼️",
    ModType.SAVE_FILE: "💾",
    ModType.CHEAT: "⚡",
}

_TYPE_LABELS = {
    ModType.TEXTURE_PACK: "Texture Packs",
    ModType.PNACH: "PNACH Patches",
    ModType.COVER_ART: "Cover Art",
    ModType.SAVE_FILE: "Save Files",
    ModType.CHEAT: "Cheats",
}


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    return f"{size_bytes / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------------------
# Single mod row shown inside a game card's mod section
# ---------------------------------------------------------------------------

class _ModRow(QFrame):
    """A compact row showing a mod with an enable/disable toggle."""

    toggled = pyqtSignal()

    def __init__(self, mod: ModInfo, db: ModDatabase, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.db = db
        self.setObjectName("mod_row")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # Type icon
        icon_lbl = QLabel(_TYPE_ICONS.get(mod.mod_type, "📦"))
        icon_lbl.setFixedWidth(20)
        icon_lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(icon_lbl)

        # Name
        name_lbl = QLabel(mod.name)
        name_lbl.setStyleSheet("color: #c8c8e8; font-size: 12px;")
        name_lbl.setWordWrap(False)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_lbl, 1)

        # Type label
        type_lbl = QLabel(_TYPE_LABELS.get(mod.mod_type, ""))
        type_lbl.setStyleSheet("color: #50507a; font-size: 10px;")
        type_lbl.setFixedWidth(100)
        layout.addWidget(type_lbl)

        # Author
        if mod.author and mod.author not in ("Unknown", ""):
            auth_lbl = QLabel(f"by {mod.author}")
            auth_lbl.setStyleSheet("color: #6070a0; font-size: 10px;")
            auth_lbl.setFixedWidth(130)
            layout.addWidget(auth_lbl)

        # Enable/disable toggle button
        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedSize(80, 24)
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)
        self._refresh_toggle()

    def _refresh_toggle(self):
        if self.mod.enabled:
            self._toggle_btn.setText("✅ Enabled")
            self._toggle_btn.setStyleSheet(
                "background:#1a4a1a; color:#60d060; border-radius:4px;"
                "font-size:10px; font-weight:bold;"
            )
        else:
            self._toggle_btn.setText("🔴 Disabled")
            self._toggle_btn.setStyleSheet(
                "background:#2a0a0a; color:#a03030; border-radius:4px;"
                "font-size:10px; font-weight:bold;"
            )

    def _on_toggle(self):
        self.mod.enabled = not self.mod.enabled
        self.db.update(self.mod)
        self._refresh_toggle()
        self.toggled.emit()


# ---------------------------------------------------------------------------
# Conflict mini-badge shown on a game card
# ---------------------------------------------------------------------------

class _ConflictBadge(QLabel):
    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setText(f"  ⚠ {count} conflict(s)  ")
        self.setStyleSheet(
            "background:#4a1a00; color:#ff9060; border-radius:4px;"
            "font-size:11px; font-weight:bold; padding:2px 6px;"
        )
        self.setToolTip(
            "These mods share overlapping files. Use the Conflicts button "
            "in the relevant mod panel to resolve them."
        )


# ---------------------------------------------------------------------------
# Per-game detail view (right pane)
# ---------------------------------------------------------------------------

class _GameDetailPane(QWidget):
    """Shows mods installed for one specific game."""

    refreshed = pyqtSignal()
    browse_requested = pyqtSignal(str)  # emits game serial

    def __init__(self, db: ModDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        self._game: Optional[GameEntry] = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # Placeholder when no game is selected
        self._placeholder = QLabel(
            "← Select a game from the list to manage its mods"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #50507a; font-size: 14px;")
        self._root.addWidget(self._placeholder)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVisible(False)
        self._root.addWidget(self._scroll, 1)

    def show_game(self, game: GameEntry):
        self._game = game
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)
        self._rebuild()

    def _rebuild(self):
        if not self._game:
            return

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title_lbl = QLabel(self._game.display_name)
        title_lbl.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #e0e0ff;"
        )
        header_row.addWidget(title_lbl, 1)

        if self._game.serial:
            serial_lbl = QLabel(self._game.serial)
            serial_lbl.setStyleSheet(
                "font-size: 12px; color: #5070c0; font-family: monospace;"
            )
            header_row.addWidget(serial_lbl)

        if self._game.serial:
            browse_btn = QPushButton("🌐 Browse Catalogue")
            browse_btn.setToolTip(
                f"Open the Browse panel filtered to mods for {self._game.serial}"
            )
            browse_btn.setStyleSheet(
                "background:#1a2a4a; color:#6090d0; border-radius:4px;"
                "font-size:11px; padding:4px 10px;"
            )
            _serial = self._game.serial
            browse_btn.clicked.connect(lambda: self.browse_requested.emit(_serial))
            header_row.addWidget(browse_btn)

        layout.addLayout(header_row)

        if self._game.size_bytes:
            size_lbl = QLabel(
                f"File: {Path(self._game.path).name}  •  {_fmt_size(self._game.size_bytes)}"
            )
            size_lbl.setStyleSheet("color: #50507a; font-size: 11px;")
            layout.addWidget(size_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #0f3460;")
        layout.addWidget(sep)

        # ── Find mods for this game ──────────────────────────────────────────
        serial = (self._game.serial or "").upper()
        all_mods = self.db.all()
        game_mods = [
            m for m in all_mods
            if m.game_id and m.game_id.upper() == serial
        ]

        # Detect conflicts among these mods
        mm = ModManager(self.db)
        conflicts = mm.detect_conflicts() if game_mods else []
        game_mod_ids = {m.id for m in game_mods}
        game_conflicts = [
            c for c in conflicts
            if c.mod_a_id in game_mod_ids or c.mod_b_id in game_mod_ids
        ]

        if not game_mods:
            empty_lbl = QLabel(
                "No mods installed for this game yet.\n\n"
                "Use the 🌐 Browse Catalogue button above to find mods, "
                "or import mods from the sidebar panels."
            )
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #50507a; font-size: 13px;")
            empty_lbl.setWordWrap(True)
            layout.addWidget(empty_lbl, 1)
        else:
            # ── Summary row ──────────────────────────────────────────────────
            enabled_count = sum(1 for m in game_mods if m.enabled)
            summary_row = QHBoxLayout()
            summary_lbl = QLabel(
                f"<b>{len(game_mods)}</b> mod(s) installed  •  "
                f"<b>{enabled_count}</b> enabled"
            )
            summary_lbl.setStyleSheet("color: #9090c0; font-size: 12px;")
            summary_row.addWidget(summary_lbl, 1)

            # Quick enable-all / disable-all
            enable_all_btn = QPushButton("✅ Enable All")
            enable_all_btn.setFixedHeight(26)
            enable_all_btn.setStyleSheet(
                "background:#1a3a1a; color:#60d060; border-radius:4px;"
                "font-size:11px; padding:0 8px;"
            )

            disable_all_btn = QPushButton("🚫 Disable All")
            disable_all_btn.setFixedHeight(26)
            disable_all_btn.setStyleSheet(
                "background:#2a0a0a; color:#d06060; border-radius:4px;"
                "font-size:11px; padding:0 8px;"
            )

            def _enable_all():
                for m in game_mods:
                    m.enabled = True
                    self.db.update(m)
                self._rebuild()
                self.refreshed.emit()

            def _disable_all():
                for m in game_mods:
                    m.enabled = False
                    self.db.update(m)
                self._rebuild()
                self.refreshed.emit()

            enable_all_btn.clicked.connect(_enable_all)
            disable_all_btn.clicked.connect(_disable_all)
            summary_row.addWidget(enable_all_btn)
            summary_row.addWidget(disable_all_btn)
            layout.addLayout(summary_row)

            if game_conflicts:
                badge = _ConflictBadge(len(game_conflicts))
                layout.addWidget(badge)

            # ── Mod rows grouped by type ─────────────────────────────────────
            for mt in (
                ModType.TEXTURE_PACK,
                ModType.PNACH,
                ModType.COVER_ART,
                ModType.SAVE_FILE,
                ModType.CHEAT,
            ):
                type_mods = [m for m in game_mods if m.mod_type == mt]
                if not type_mods:
                    continue

                group_label = QLabel(
                    f"{_TYPE_ICONS[mt]}  {_TYPE_LABELS[mt]}"
                )
                group_label.setStyleSheet(
                    "font-weight: bold; color: #8090c0; font-size: 13px;"
                    "margin-top: 8px;"
                )
                layout.addWidget(group_label)

                for mod in type_mods:
                    row = _ModRow(mod, self.db)
                    row.toggled.connect(self.refreshed.emit)
                    layout.addWidget(row)

        layout.addStretch()
        self._scroll.setWidget(container)


# ---------------------------------------------------------------------------
# Game card shown in the left list
# ---------------------------------------------------------------------------

class _GameCard(QFrame):
    """A clickable card representing one game in the library."""

    clicked = pyqtSignal(object)  # emits the GameEntry

    def __init__(self, game: GameEntry, mod_count: int, parent=None, config=None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Cover art thumbnail (48×68 px) or disc icon fallback
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(48, 68)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            "background: #0a0a1a; border: 1px solid #1a1a3a; border-radius: 3px;"
        )
        thumb_loaded = False
        if game.serial:
            from PyQt6.QtGui import QPixmap
            from src.core.config_manager import THUMBNAILS_DIR

            # Search order: PCSX2 covers folder → app thumbnail cache
            cover_art_search_paths: list[Path] = []
            if config:
                cover_dir = getattr(config, "cover_art_path", "") or ""
                if cover_dir and Path(cover_dir).is_dir():
                    cover_art_search_paths.append(Path(cover_dir))
            cover_art_search_paths.append(THUMBNAILS_DIR)

            for search_dir in cover_art_search_paths:
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    thumb_path = search_dir / f"{game.serial}{ext}"
                    if thumb_path.is_file():
                        px = QPixmap(str(thumb_path))
                        if not px.isNull():
                            thumb_lbl.setPixmap(
                                px.scaled(48, 68,
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
                            )
                            thumb_loaded = True
                            break
                if thumb_loaded:
                    break
        if not thumb_loaded:
            thumb_lbl.setText("💿")
            thumb_lbl.setStyleSheet(
                "font-size: 26px; background: #0a0a1a; "
                "border: 1px solid #1a1a3a; border-radius: 3px;"
            )
        layout.addWidget(thumb_lbl)

        # Info column
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_lbl = QLabel(game.title or game.filename)
        name_lbl.setStyleSheet("font-weight: bold; color: #d0d0f0; font-size: 13px;")
        name_lbl.setWordWrap(False)
        info_col.addWidget(name_lbl)

        sub_parts = []
        if game.serial:
            sub_parts.append(game.serial)
        if game.size_bytes:
            sub_parts.append(_fmt_size(game.size_bytes))
        if sub_parts:
            sub_lbl = QLabel("  •  ".join(sub_parts))
            sub_lbl.setStyleSheet("color: #50507a; font-size: 10px;")
            info_col.addWidget(sub_lbl)

        layout.addLayout(info_col, 1)

        # Mod count badge
        if mod_count > 0:
            mc_lbl = QLabel(f"  {mod_count} mod(s)  ")
            mc_lbl.setStyleSheet(
                "background:#1a2a4a; color:#6090d0; border-radius:4px;"
                "font-size:10px; padding:2px 4px;"
            )
            layout.addWidget(mc_lbl)

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.setStyleSheet(
                "QFrame#card { background: #1a2a4a; border: 1px solid #3060c0; }"
            )
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.game)


# ---------------------------------------------------------------------------
# "View All Mods" flat pane — searchable, filterable list of all mods
# ---------------------------------------------------------------------------

class _AllModsPane(QWidget):
    """Flat list of every mod in the database with search/filter controls."""

    def __init__(self, db: ModDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows: list[_ModRow] = []
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Filter bar ──────────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        search_lbl = QLabel("🔍")
        search_lbl.setStyleSheet("color: #70a0d0; font-size: 13px;")
        filter_bar.addWidget(search_lbl)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search by name, game, or author…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._search_edit, 1)

        type_lbl = QLabel("Type:")
        type_lbl.setStyleSheet("color: #9090b0; font-size: 11px;")
        filter_bar.addWidget(type_lbl)

        self._type_combo = QComboBox()
        self._type_combo.addItem("All types", "")
        for mt in ModType:
            self._type_combo.addItem(mt.value, mt.value)
        self._type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._type_combo)

        status_lbl = QLabel("Status:")
        status_lbl.setStyleSheet("color: #9090b0; font-size: 11px;")
        filter_bar.addWidget(status_lbl)

        self._status_combo = QComboBox()
        self._status_combo.addItem("All", "all")
        self._status_combo.addItem("✅ Enabled", "enabled")
        self._status_combo.addItem("🔴 Disabled", "disabled")
        self._status_combo.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._status_combo)

        layout.addLayout(filter_bar)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #606080; font-size: 11px;")
        layout.addWidget(self._count_lbl)

        # ── Scrollable mod list ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        layout.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    def refresh(self):
        """Reload all mods from the DB and re-apply the filter."""
        # Clear existing rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        all_mods = self.db.all()
        for mod in sorted(all_mods, key=lambda m: (m.name or "").lower()):
            row = _ModRow(mod, self.db)
            row.toggled.connect(self.refresh)
            self._rows.append(row)
            self._list_layout.addWidget(row)
        self._list_layout.addStretch()

        self._apply_filter()

    # ------------------------------------------------------------------
    def _apply_filter(self):
        needle = self._search_edit.text().strip().lower()
        type_filter = self._type_combo.currentData() or ""
        status_filter = self._status_combo.currentData() or "all"

        shown = 0
        for row in self._rows:
            mod = row.mod

            # Name / game / author search
            if needle:
                haystack = " ".join([
                    mod.name or "",
                    mod.game_id or "",
                    mod.author or "",
                    (mod.mod_type.value if mod.mod_type else ""),
                ]).lower()
                if needle not in haystack:
                    row.setVisible(False)
                    continue

            # Type filter
            if type_filter and mod.mod_type and mod.mod_type.value != type_filter:
                row.setVisible(False)
                continue

            # Status filter
            if status_filter == "enabled" and not mod.enabled:
                row.setVisible(False)
                continue
            if status_filter == "disabled" and mod.enabled:
                row.setVisible(False)
                continue

            row.setVisible(True)
            shown += 1

        total = len(self._rows)
        self._count_lbl.setText(
            f"Showing {shown} of {total} mod(s)"
            + (" — no mods installed yet" if total == 0 else "")
        )


# ---------------------------------------------------------------------------
# My Library Panel
# ---------------------------------------------------------------------------

class LibraryPanel(BasePanel):
    """
    Shows all PS2 disc images from the user's game library folder.
    Clicking a game opens a per-game mod management view on the right.
    """

    # Emitted when the user clicks "Browse Catalogue" for a specific serial
    browse_game = pyqtSignal(str)  # emits game serial

    def __init__(self, db: ModDatabase, config: AppConfig, parent=None):
        super().__init__("🎮  My Library", "Enable and disable mods for each game", parent)
        self.db = db
        self.config = config
        self._cards: list[_GameCard] = []
        self._selected_card: Optional[_GameCard] = None
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        content = self._content_layout

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        refresh_btn = QPushButton("↺ Scan Library")
        refresh_btn.setObjectName("primary_btn")
        refresh_btn.setToolTip("Re-scan your game library folder and refresh the list")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        import_btn = QPushButton("📂 Import Installed Content")
        import_btn.setToolTip(
            "Scan your PCSX2 folder for texture packs, PNACH files, and cover art\n"
            "that were installed outside of PS2 Mod Manager so you can manage them here"
        )
        import_btn.clicked.connect(self._open_installed_scanner)
        toolbar.addWidget(import_btn)

        conflict_btn = QPushButton("⚠ Resolve Conflicts")
        conflict_btn.setToolTip(
            "Scan your installed PCSX2 content for conflicts:\n"
            "• Duplicate PNACH files across cheats/ and cheats_ws/\n"
            "• PNACH patches writing to the same memory address\n"
            "• Multiple cover-art images for the same serial\n"
            "• Merged texture packs that may override each other"
        )
        conflict_btn.clicked.connect(self._open_conflict_resolver)
        toolbar.addWidget(conflict_btn)

        toolbar.addStretch()

        # ── View mode toggle ──────────────────────────────────────────────
        self._by_game_btn = QPushButton("🎮 By Game")
        self._by_game_btn.setCheckable(True)
        self._by_game_btn.setChecked(True)
        self._by_game_btn.setToolTip("View mods grouped by game (default)")
        self._by_game_btn.clicked.connect(self._switch_to_by_game)
        toolbar.addWidget(self._by_game_btn)

        self._all_mods_btn = QPushButton("📋 All Mods")
        self._all_mods_btn.setCheckable(True)
        self._all_mods_btn.setChecked(False)
        self._all_mods_btn.setToolTip("View all installed mods in a flat searchable list")
        self._all_mods_btn.clicked.connect(self._switch_to_all_mods)
        toolbar.addWidget(self._all_mods_btn)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        toolbar.addWidget(self._count_lbl)

        content.addLayout(toolbar)

        # ── Mode stack: By Game (index 0) | All Mods (index 1) ──────────
        self._mode_stack = QStackedWidget()

        # ── By-Game widget ────────────────────────────────────────────────
        by_game_widget = QWidget()
        by_game_layout = QVBoxLayout(by_game_widget)
        by_game_layout.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(4)

        # Left: game list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(4)

        self._scroll.setWidget(self._list_container)
        left_layout.addWidget(self._scroll, 1)
        left_widget.setMinimumWidth(240)
        left_widget.setMaximumWidth(380)

        # Right: detail pane
        self._detail = _GameDetailPane(self.db)
        self._detail.refreshed.connect(self._on_mod_toggled)
        self._detail.browse_requested.connect(self.browse_game)

        self._splitter.addWidget(left_widget)
        self._splitter.addWidget(self._detail)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        by_game_layout.addWidget(self._splitter)
        self._mode_stack.addWidget(by_game_widget)

        # ── All-Mods widget ───────────────────────────────────────────────
        self._all_mods_pane = _AllModsPane(self.db)
        self._mode_stack.addWidget(self._all_mods_pane)

        content.addWidget(self._mode_stack, 1)

        # Initial populate (By Game mode)
        self._populate()

    # ------------------------------------------------------------------
    # View mode switching
    # ------------------------------------------------------------------

    def _switch_to_by_game(self):
        self._by_game_btn.setChecked(True)
        self._all_mods_btn.setChecked(False)
        self._mode_stack.setCurrentIndex(0)
        self._populate()

    def _switch_to_all_mods(self):
        self._by_game_btn.setChecked(False)
        self._all_mods_btn.setChecked(True)
        self._mode_stack.setCurrentIndex(1)
        self._all_mods_pane.refresh()
        total = len(self.db.all())
        enabled = sum(1 for m in self.db.all() if m.enabled)
        self._count_lbl.setText(f"{total} mod(s)  •  {enabled} enabled")

    # ------------------------------------------------------------------
    # Populate game list
    # ------------------------------------------------------------------

    def _populate(self):
        # Clear current list
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()
        self._selected_card = None

        library_path = getattr(self.config, "game_library_path", "")
        if not library_path:
            # Try to auto-detect from pcsx2_path
            pcsx2_path = getattr(self.config, "pcsx2_path", "") or ""
            auto_hint = ""
            if pcsx2_path:
                for sub in ("roms", "ISOs", "iso", "games", "Games"):
                    candidate = str(Path(pcsx2_path) / sub)
                    if Path(candidate).is_dir():
                        auto_hint = candidate
                        break

            if auto_hint:
                msg = QLabel(
                    "Game library path not configured.\n\n"
                    f"💡 Found a possible ROM folder:\n{auto_hint}\n\n"
                    "Go to ⚙ Settings → Game Library Path to set it."
                )
            else:
                msg = QLabel(
                    "Game library path not configured.\n\n"
                    "Go to ⚙ Settings and set your Game Library folder\n"
                    "(the folder where you keep your .iso / .chd files)."
                )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet("color: #50507a; font-size: 13px;")
            msg.setWordWrap(True)
            self._list_layout.addWidget(msg)
            self._count_lbl.setText("Not configured")

            # Still show DB-tracked games even without a library path
            self._populate_db_games()
            return

        games = scan_library(library_path)

        if not games:
            placeholder = QLabel(
                "No PS2 disc images found in your game library.\n\n"
                "Make sure your folder contains .iso, .chd, or other PS2 disc images."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #50507a; font-size: 13px;")
            placeholder.setWordWrap(True)
            self._list_layout.addWidget(placeholder)
            self._count_lbl.setText("0 games")

            # Still show DB-tracked games even if no ISO files were found
            self._populate_db_games()
            return

        # Count mods per serial
        all_mods = self.db.all()
        mods_by_serial: dict[str, int] = {}
        for m in all_mods:
            if m.game_id:
                key = m.game_id.upper()
                mods_by_serial[key] = mods_by_serial.get(key, 0) + 1

        # Track which serials are covered by library files
        library_serials: set[str] = set()
        for game in games:
            serial_key = (game.serial or "").upper()
            mod_count = mods_by_serial.get(serial_key, 0)
            card = _GameCard(game, mod_count, config=self.config)
            card.clicked.connect(self._on_game_clicked)
            self._list_layout.addWidget(card)
            self._cards.append(card)
            if serial_key:
                library_serials.add(serial_key)

        # Add DB-only games (have mods but no matching ISO in the library)
        db_only_games = self._get_db_only_games(library_serials)
        if db_only_games:
            sep_lbl = QLabel("── Installed (no disc image) ──")
            sep_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sep_lbl.setStyleSheet("color: #404070; font-size: 10px; margin-top: 4px;")
            self._list_layout.addWidget(sep_lbl)
            for game, mod_count in db_only_games:
                card = _GameCard(game, mod_count, config=self.config)
                card.clicked.connect(self._on_game_clicked)
                self._list_layout.addWidget(card)
                self._cards.append(card)

        self._list_layout.addStretch()

        total = len(games) + len(db_only_games)
        games_with_mods = sum(1 for g in games if mods_by_serial.get((g.serial or "").upper(), 0) > 0)
        games_with_mods += len(db_only_games)
        self._count_lbl.setText(
            f"{total} game(s)  •  {games_with_mods} have mods installed"
        )

    # ------------------------------------------------------------------
    # DB-game helpers
    # ------------------------------------------------------------------

    def _get_db_only_games(self, exclude_serials: set[str]) -> list[tuple[GameEntry, int]]:
        """Build GameEntry objects for serials in the mod DB that aren't in exclude_serials."""
        from src.core.game_registry import lookup_game_title
        all_mods = self.db.all()
        serials_with_mods: dict[str, int] = {}
        for m in all_mods:
            if m.game_id:
                key = m.game_id.upper()
                serials_with_mods[key] = serials_with_mods.get(key, 0) + 1

        result: list[tuple[GameEntry, int]] = []
        for serial, mod_count in sorted(serials_with_mods.items()):
            if serial in exclude_serials:
                continue
            title = lookup_game_title(serial) or serial
            entry = GameEntry(
                path="",
                filename="",
                serial=serial,
                title=title,
                size_bytes=0,
            )
            result.append((entry, mod_count))
        return result

    def _populate_db_games(self):
        """Add game cards for all serials that have mods in the DB."""
        db_only = self._get_db_only_games(set())
        if not db_only:
            return
        sep_lbl = QLabel("── Games with installed mods ──")
        sep_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep_lbl.setStyleSheet("color: #404070; font-size: 10px; margin-top: 4px;")
        self._list_layout.addWidget(sep_lbl)
        for game, mod_count in db_only:
            card = _GameCard(game, mod_count, config=self.config)
            card.clicked.connect(self._on_game_clicked)
            self._list_layout.addWidget(card)
            self._cards.append(card)
        self._list_layout.addStretch()
        self._count_lbl.setText(f"{len(db_only)} game(s) with mods installed")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_game_clicked(self, game: GameEntry):
        # Deselect previous
        if self._selected_card:
            self._selected_card.set_selected(False)

        # Select new
        for card in self._cards:
            if card.game is game:
                card.set_selected(True)
                self._selected_card = card
                break

        self._detail.show_game(game)

    def _on_mod_toggled(self):
        """Refresh the game list counts after a mod toggle."""
        if self._mode_stack.currentIndex() == 1:
            self._all_mods_pane.refresh()
            return
        self._populate()
        # Re-select the game if one was selected
        if self._selected_card:
            game = self._selected_card.game
            for card in self._cards:
                if card.game.path == game.path:
                    card.set_selected(True)
                    self._selected_card = card
                    self._detail.show_game(game)
                    break

    def refresh(self):
        if self._mode_stack.currentIndex() == 1:
            self._switch_to_all_mods()
        else:
            self._populate()
        self.emit_status("Library refreshed")

    def _open_installed_scanner(self):
        """Open the Installed Content Scanner dialog (import from PCSX2 folder)."""
        from src.ui.widgets import InstalledScannerDialog
        dlg = InstalledScannerDialog(self.config, self)
        dlg.exec()
        # Refresh whichever mode is active
        self.refresh()

    def _open_conflict_resolver(self):
        """Open the Conflict Resolver dialog."""
        from src.ui.widgets import ConflictResolverDialog
        dlg = ConflictResolverDialog(self.config, self)
        dlg.exec()
