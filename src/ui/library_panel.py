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
    QFrame,
    QHBoxLayout,
    QLabel,
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
                "Browse the catalogue or import mods from the sidebar panels."
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

    def __init__(self, game: GameEntry, mod_count: int, parent=None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Disc icon
        disc_lbl = QLabel("💿")
        disc_lbl.setStyleSheet("font-size: 22px;")
        disc_lbl.setFixedWidth(28)
        layout.addWidget(disc_lbl)

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
# My Library Panel
# ---------------------------------------------------------------------------

class LibraryPanel(BasePanel):
    """
    Shows all PS2 disc images from the user's game library folder.
    Clicking a game opens a per-game mod management view on the right.
    """

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
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        toolbar.addWidget(self._count_lbl)
        toolbar.addStretch()

        content.addLayout(toolbar)

        # ── Main splitter (game list | detail pane) ───────────────────────
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

        self._splitter.addWidget(left_widget)
        self._splitter.addWidget(self._detail)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        content.addWidget(self._splitter, 1)

        # Initial populate
        self._populate()

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
            placeholder = QLabel(
                "Game library path not configured.\n\n"
                "Go to ⚙ Settings and set your Game Library folder."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #50507a; font-size: 13px;")
            placeholder.setWordWrap(True)
            self._list_layout.addWidget(placeholder)
            self._count_lbl.setText("Not configured")
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
            return

        # Count mods per serial
        all_mods = self.db.all()
        mods_by_serial: dict[str, int] = {}
        for m in all_mods:
            if m.game_id:
                key = m.game_id.upper()
                mods_by_serial[key] = mods_by_serial.get(key, 0) + 1

        for game in games:
            serial_key = (game.serial or "").upper()
            mod_count = mods_by_serial.get(serial_key, 0)
            card = _GameCard(game, mod_count)
            card.clicked.connect(self._on_game_clicked)
            self._list_layout.addWidget(card)
            self._cards.append(card)

        self._list_layout.addStretch()

        total = len(games)
        games_with_mods = sum(1 for g in games if mods_by_serial.get((g.serial or "").upper(), 0) > 0)
        self._count_lbl.setText(
            f"{total} game(s) found  •  {games_with_mods} have mods installed"
        )

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
        self._populate()
        self.emit_status("Library refreshed")
