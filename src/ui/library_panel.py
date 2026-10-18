"""My Library panel — per-game view of installed mods.

Scans the user's game library folder (set in Settings → Game Library Path),
displays each discovered PS2 disc image as a clickable game card, and lets
the user enable / disable individual mods that target that game.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot
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
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import save_config
from src.core.game_library import GameEntry, scan_library
from src.core.game_registry import lookup_game_title
from src.core.mod_manager import ModDatabase, ModManager
from src.core.mod_search import (
    MOD_SEARCH_HELP, MOD_SEARCH_HINT, compile_mod_query,
    mod_matches_query as _mod_matches_query,
)
from src.models.mod import AppConfig, ModInfo, ModType
from src.ui.base_panel import BasePanel

logger = logging.getLogger(__name__)


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


def _block_signals(widget, blocked: bool) -> None:
    setter = getattr(widget, "blockSignals", None)
    if callable(setter):
        setter(blocked)


def _library_ui_state(config: AppConfig) -> dict:
    ui_state = getattr(config, "ui_state", None)
    if not isinstance(ui_state, dict):
        ui_state = {}
        config.ui_state = ui_state
    library_state = ui_state.setdefault("library_panel", {})
    if not isinstance(library_state, dict):
        library_state = {}
        ui_state["library_panel"] = library_state
    return library_state


def _save_library_config(config: AppConfig, context: str) -> None:
    try:
        save_config(config)
    except Exception as exc:
        logger.warning("Could not save library panel config after %s: %s", context, exc)


def _game_matches_search(game: GameEntry, terms: list[tuple[str, str]]) -> bool:
    if not terms:
        return True
    values = (
        game.title, game.serial, game.filename, game.path,
        game.region, game.disc_type if game.path else "", *game.crcs,
    )
    normalized = [
        (value.casefold(), "".join(ch for ch in value.casefold() if ch.isalnum()))
        for value in values
    ]
    return all(
        any(text in value or (compact and compact in compact_value)
            for value, compact_value in normalized)
        for text, compact in terms
    )


# ---------------------------------------------------------------------------
# Single mod row shown inside a game card's mod section
# ---------------------------------------------------------------------------

class _ModRow(QFrame):
    """A compact row showing a mod with an enable/disable toggle."""

    toggle_requested = pyqtSignal(str, bool)

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
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_lbl.setStyleSheet("color: #c8c8e8; font-size: 12px;")
        name_lbl.setWordWrap(True)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(name_lbl)
        if mod.author and mod.author not in ("Unknown", ""):
            auth_lbl = QLabel(f"by {mod.author}")
            auth_lbl.setTextFormat(Qt.TextFormat.PlainText)
            auth_lbl.setStyleSheet("color: #6070a0; font-size: 10px;")
            auth_lbl.setWordWrap(True)
            info.addWidget(auth_lbl)
        layout.addLayout(info, 1)

        # Type label
        type_lbl = QLabel(_TYPE_LABELS.get(mod.mod_type, ""))
        type_lbl.setStyleSheet("color: #50507a; font-size: 10px;")
        type_lbl.setFixedWidth(100)
        layout.addWidget(type_lbl)

        # Enable/disable toggle button
        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedSize(100, 28)
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)
        self._refresh_toggle()

    def _refresh_toggle(self):
        action = "Disable" if self.mod.enabled else "Enable"
        self._toggle_btn.setAccessibleName(f"{action} {self.mod.name}")
        self._toggle_btn.setToolTip(
            "Change this library flag only; live memory-card files are never copied or removed."
            if self.mod.mod_type == ModType.SAVE_FILE else
            f"{action} this mod and reconcile its configured PCSX2 destination. "
            "Other enabled mods of the affected type are re-deployed to preserve priorities and shared files."
        )
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
        self.toggle_requested.emit(self.mod.id, not self.mod.enabled)


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

    enabled_requested = pyqtSignal(object, str, bool)
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

    def clear_game(self):
        self._game = None
        self._scroll.setVisible(False)
        self._placeholder.setVisible(True)

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
        title_lbl.setWordWrap(True)  # issue #22: wrap long titles so they don't get cut off
        header_row.addWidget(title_lbl, 1)

        if self._game.serial:
            serial_lbl = QLabel(self._game.serial)
            serial_lbl.setStyleSheet(
                "font-size: 12px; color: #5070c0; font-family: monospace;"
            )
            header_row.addWidget(serial_lbl)

        if self._game.serial:
            game_actions = QHBoxLayout()
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
            game_actions.addWidget(browse_btn)

            load_order_btn = QPushButton("⬆⬇ Load Order")
            load_order_btn.setToolTip(
                "Set the priority order for mods installed for this game.\n"
                "Mods listed lower override those above (last-write wins)."
            )
            load_order_btn.setStyleSheet(
                "background:#1a1a3a; color:#9090d0; border-radius:4px;"
                "font-size:11px; padding:4px 10px;"
            )
            load_order_btn.clicked.connect(lambda: self._open_load_order(_serial))
            game_actions.addWidget(load_order_btn)
            game_actions.addStretch()

        layout.addLayout(header_row)
        if self._game.serial:
            layout.addLayout(game_actions)

        # ── Identity row: serial, region, disc type, CRCs, file path ────────
        id_parts: list[str] = []
        if self._game.serial:
            id_parts.append(self._game.serial)
        if self._game.region:
            id_parts.append(self._game.region)
        id_parts.append(self._game.disc_type)

        id_row = QHBoxLayout()
        id_row.setSpacing(6)

        if id_parts:
            identity_lbl = QLabel("  •  ".join(id_parts))
            identity_lbl.setStyleSheet(
                "color: #7070a0; font-size: 11px; font-family: monospace;"
            )
            id_row.addWidget(identity_lbl)

        # CRC badge(s) — each CRC is important for PCSX2
        for crc in self._game.crcs:
            crc_lbl = QLabel(f"CRC: {crc}")
            crc_lbl.setToolTip(
                f"PCSX2 CRC: {crc}\n"
                "This is the game's internal checksum used by PCSX2 to name\n"
                "PNACH cheat files and texture replacement folders."
            )
            crc_lbl.setStyleSheet(
                "background:#0a1a0a; color:#40c060; border:1px solid #205020;"
                "border-radius:3px; font-size:10px; font-family:monospace;"
                "padding:1px 5px;"
            )
            id_row.addWidget(crc_lbl)

        id_row.addStretch()
        layout.addLayout(id_row)

        if self._game.path:
            file_parts = [f"📁 {Path(self._game.path).name}"]
            if self._game.size_bytes:
                file_parts.append(_fmt_size(self._game.size_bytes))
            path_lbl = QLabel("  •  ".join(file_parts))
            path_lbl.setStyleSheet("color: #50507a; font-size: 11px;")
            path_lbl.setToolTip(self._game.path)
            layout.addWidget(path_lbl)

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
            summary_lbl.setWordWrap(True)
            layout.addWidget(summary_lbl)

            # Quick enable-all / disable-all
            enable_count = sum(not mod.enabled for mod in game_mods)
            disable_count = len(game_mods) - enable_count
            enable_all_btn = QPushButton(f"Enable Game Mods ({enable_count})")
            enable_all_btn.setEnabled(bool(enable_count))
            enable_all_btn.setToolTip("Enable disabled mods for this game only, across all content types.")
            enable_all_btn.setFixedHeight(26)
            enable_all_btn.setStyleSheet(
                "background:#1a3a1a; color:#60d060; border-radius:4px;"
                "font-size:11px; padding:0 8px;"
            )

            disable_all_btn = QPushButton(f"Disable Game Mods ({disable_count})")
            disable_all_btn.setEnabled(bool(disable_count))
            disable_all_btn.setToolTip("Disable enabled mods for this game only, across all content types.")
            disable_all_btn.setFixedHeight(26)
            disable_all_btn.setStyleSheet(
                "background:#2a0a0a; color:#d06060; border-radius:4px;"
                "font-size:11px; padding:0 8px;"
            )

            enable_all_btn.clicked.connect(lambda: self._request_game_enabled(True))
            disable_all_btn.clicked.connect(lambda: self._request_game_enabled(False))
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
                    row.toggle_requested.connect(self._request_mod_enabled)
                    layout.addWidget(row)

        layout.addStretch()
        self._scroll.setWidget(container)

    def _request_mod_enabled(self, mod_id, enabled):
        self.enabled_requested.emit({mod_id: enabled}, "Single mod in By Game", False)

    def _request_game_enabled(self, enabled):
        if self._game is None or not self._game.serial:
            return
        serial = self._game.serial.upper()
        states = {
            mod.id: enabled for mod in self.db.all()
            if mod.game_id and mod.game_id.upper() == serial and mod.enabled != enabled
        }
        if states:
            self.enabled_requested.emit(states, f"Game {serial} — all installed content types", True)

    def _open_load_order(self, serial: str):
        """Open the Load Order dialog for *serial*."""
        from src.ui.widgets import LoadOrderDialog
        dlg = LoadOrderDialog(serial, self.db, parent=self)
        dlg.exec()


# ---------------------------------------------------------------------------
# Game card shown in the left list
# ---------------------------------------------------------------------------

class _GameCard(QFrame):
    """A clickable card representing one game in the library."""

    clicked = pyqtSignal(object)  # emits the GameEntry

    def __init__(self, game: GameEntry, mod_count: int, parent=None, config=None):
        super().__init__(parent)
        self.game = game
        self.mod_count = mod_count
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        focus_policy = getattr(getattr(Qt, "FocusPolicy", None), "StrongFocus", None)
        if focus_policy is not None:
            self.setFocusPolicy(focus_policy)
        self.setAccessibleName(f"Game card: {game.display_name}")
        self.setAccessibleDescription(
            "Press Enter or Space to select this game and manage its mods."
        )
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
                    # Issue #33: try exact serial, lowercase serial, and serial with dash replaced by underscore
                    candidates = [
                        search_dir / f"{game.serial}{ext}",
                        search_dir / f"{game.serial.lower()}{ext}",
                        search_dir / f"{game.serial.replace('-', '_')}{ext}",
                    ]
                    for thumb_path in candidates:
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
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_lbl.setToolTip(game.path or "Tracked game with installed mods; no disc image found")
        name_lbl.setStyleSheet("font-weight: bold; color: #d0d0f0; font-size: 13px;")
        name_lbl.setWordWrap(True)  # issue #32: wrap long game names instead of horizontal scroll
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_col.addWidget(name_lbl)
        sub_parts = []
        if game.serial:
            sub_parts.append(game.serial)
        if game.region:
            sub_parts.append(game.region)
        sub_parts.append(game.disc_type if game.path else "No disc image")
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

    def keyPressEvent(self, event):
        key = getattr(event, "key", lambda: None)()
        activate_keys = {
            getattr(getattr(Qt, "Key", None), "Key_Return", None),
            getattr(getattr(Qt, "Key", None), "Key_Enter", None),
            getattr(getattr(Qt, "Key", None), "Key_Space", None),
        }
        if key in activate_keys:
            accept = getattr(event, "accept", None)
            if callable(accept):
                accept()
            self.clicked.emit(self.game)
            return
        key_press = getattr(super(), "keyPressEvent", None)
        if callable(key_press):
            key_press(event)


# ---------------------------------------------------------------------------
# "View All Mods" flat pane — searchable, filterable list of all mods
# ---------------------------------------------------------------------------

class _AllModsPane(QWidget):
    """Flat list of every mod in the database with search/filter controls."""

    enabled_requested = pyqtSignal(object, str, bool)

    def __init__(self, db: ModDatabase, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._state_persistence_enabled = False
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
        self._search_edit.setPlaceholderText(
            "Search by name, game title, serial, author, tag, file, or source URL…"
        )
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setAccessibleName("Search all installed mods")
        self._search_edit.setToolTip(MOD_SEARCH_HELP)
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
        help_row = QHBoxLayout()
        hint = QLabel(MOD_SEARCH_HINT)
        hint.setWordWrap(True)
        hint.setToolTip(MOD_SEARCH_HELP)
        help_row.addWidget(hint, 1)
        self._clear_filters_btn = QPushButton("Clear Filters")
        self._clear_filters_btn.clicked.connect(self._clear_filters)
        help_row.addWidget(self._clear_filters_btn)
        layout.addLayout(help_row)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #606080; font-size: 11px;")
        layout.addWidget(self._count_lbl)
        self._empty_lbl = QLabel()
        self._empty_lbl.setWordWrap(True)
        layout.addWidget(self._empty_lbl)

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

    def _state_bucket(self) -> dict:
        state = _library_ui_state(self.config)
        pane_state = state.setdefault("all_mods", {})
        if not isinstance(pane_state, dict):
            pane_state = {}
            state["all_mods"] = pane_state
        return pane_state

    def restore_filter_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return

        should_save = False
        _block_signals(self._search_edit, True)
        _block_signals(self._type_combo, True)
        _block_signals(self._status_combo, True)
        try:
            self._search_edit.setText(str(state.get("search", "")))

            type_filter = str(state.get("type", "") or "")
            type_idx = self._type_combo.findData(type_filter)
            if type_idx >= 0:
                self._type_combo.setCurrentIndex(type_idx)
                state["type"] = type_filter
            else:
                logger.warning(
                    "Saved library-panel type filter %r is no longer available; using All Types",
                    type_filter,
                )
                self._type_combo.setCurrentIndex(0)
                state["type"] = ""
                should_save = True

            status_filter = str(state.get("status", "all") or "all")
            status_idx = self._status_combo.findData(status_filter)
            if status_idx >= 0:
                self._status_combo.setCurrentIndex(status_idx)
                state["status"] = status_filter
            else:
                logger.warning(
                    "Saved library-panel status filter %r is no longer available; using All",
                    status_filter,
                )
                self._status_combo.setCurrentIndex(0)
                state["status"] = "all"
                should_save = True
        finally:
            _block_signals(self._search_edit, False)
            _block_signals(self._type_combo, False)
            _block_signals(self._status_combo, False)

        if should_save:
            _save_library_config(self.config, "sanitizing library panel filter state")

    def current_filter_state(self) -> dict:
        return {
            "search": self._search_edit.text(),
            "type": self._type_combo.currentData() or "",
            "status": self._status_combo.currentData() or "all",
        }

    def _save_filter_state(self, context: str) -> None:
        if not getattr(self, "_state_persistence_enabled", False):
            return
        self._state_bucket().update(self.current_filter_state())
        _save_library_config(self.config, context)

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
            row.toggle_requested.connect(self._request_mod_enabled)
            self._rows.append(row)
            self._list_layout.addWidget(row)
        self._list_layout.addStretch()

        self._apply_filter()

    def _request_mod_enabled(self, mod_id, enabled):
        self.enabled_requested.emit({mod_id: enabled}, "Single mod in All Mods", False)

    # ------------------------------------------------------------------
    def _apply_filter(self):
        needle = self._search_edit.text().strip()
        search = compile_mod_query(needle)
        type_filter = self._type_combo.currentData() or ""
        status_filter = self._status_combo.currentData() or "all"

        shown = 0
        for row in self._rows:
            mod = row.mod

            # Rich metadata search across local mod and game fields
            if not search.matches(mod):
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
            f"Showing {shown} of {total} tracked mod(s) in library"
            + (" — no mods installed yet" if total == 0 else "")
        )
        self._empty_lbl.setText(
            "No mods match these filters. Use Clear Filters to show all installed mods."
            if total else "No installed mods yet. Import mods from a content panel or Browse."
        )
        self._empty_lbl.setVisible(shown == 0)
        self._save_filter_state("updating all-mods filters")

    def _clear_filters(self):
        for widget in (self._search_edit, self._type_combo, self._status_combo):
            _block_signals(widget, True)
        try:
            self._search_edit.clear()
            self._type_combo.setCurrentIndex(0)
            self._status_combo.setCurrentIndex(0)
        finally:
            for widget in (self._search_edit, self._type_combo, self._status_combo):
                _block_signals(widget, False)
        self._apply_filter()


# ---------------------------------------------------------------------------
# My Library Panel
# ---------------------------------------------------------------------------

class _LibraryScanResult(QObject):
    finished = pyqtSignal(int, str, object, str)


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
        self.manager = ModManager(self.db)
        self._cards: list[_GameCard] = []
        self._shown_cards: list[_GameCard] = []
        self._selected_card: Optional[_GameCard] = None
        self._library_scan_cache_path: Optional[str] = None
        self._library_scan_cache: list[GameEntry] = []
        self._last_library_status: str = ""
        self._library_scan_error: str = ""
        self._library_scan_error_path: Optional[str] = None
        self._scan_generation = 0
        self._scan_requested_path: Optional[str] = None
        self._scan_active = None
        self._scan_pending = None
        self._rendered_library_path: Optional[str] = None
        self._state_persistence_enabled = False
        self._mod_action_busy = False
        self._mod_retry_states = {}
        self._mod_retry_scope = ""
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

        # Issue #7: "Port installed content" button removed — content is detected automatically.
        # The conflict resolver is still available for manual conflict management.

        conflict_btn = QPushButton("⚠ Resolve Conflicts")
        conflict_btn.setToolTip(
            "Scan your installed PCSX2 content for conflicts:\n"
            "• Duplicate PNACH files across cheats/ and cheats_ws/\n"
            "• PNACH patches writing to the same memory address\n"
            "• Multiple cover-art images for the same serial\n"
            "• Duplicate texture files with identical content"
        )
        conflict_btn.clicked.connect(self._open_conflict_resolver)
        toolbar.addWidget(conflict_btn)

        toolbar.addStretch()

        # ── Profiles button ───────────────────────────────────────────────
        profiles_btn = QPushButton("👤 Profiles")
        profiles_btn.setToolTip(
            "Manage named mod profiles — save, load, and switch between "
            "preset configurations like 'Vanilla+' or 'HD Graphics'"
        )
        profiles_btn.clicked.connect(self._open_profiles_dialog)
        toolbar.addWidget(profiles_btn)

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

        # Issue #20: count label placed on its own row below toolbar to avoid overflow
        content.addLayout(toolbar)

        # Count label on its own row so it never forces a horizontal scroll bar (issue #20)
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        self._count_lbl.setWordWrap(True)
        content.addWidget(self._count_lbl)
        self._scan_status = QLabel()
        self._scan_status.setWordWrap(True)
        self._scan_status.setTextFormat(Qt.TextFormat.PlainText)
        self._scan_status.hide()
        content.addWidget(self._scan_status)
        self._mod_feedback = QTextEdit()
        self._mod_feedback.setReadOnly(True)
        self._mod_feedback.setMaximumHeight(110)
        self._mod_feedback.setAccessibleName("Library mod action result")
        self._mod_feedback.hide()
        content.addWidget(self._mod_feedback)
        result_actions = QHBoxLayout()
        self._mod_retry_btn = QPushButton("Retry Original Action")
        self._mod_retry_btn.setToolTip(
            "Review and retry only the original mod IDs and requested states, even if filters now hide them."
        )
        self._mod_retry_btn.clicked.connect(self._retry_mod_action)
        self._mod_retry_btn.hide()
        result_actions.addWidget(self._mod_retry_btn)
        self._mod_dismiss_btn = QPushButton("Dismiss Result")
        self._mod_dismiss_btn.setToolTip("Forget this result and retry snapshot; this does not undo saved changes.")
        self._mod_dismiss_btn.clicked.connect(self._dismiss_mod_result)
        self._mod_dismiss_btn.hide()
        result_actions.addWidget(self._mod_dismiss_btn)
        result_actions.addStretch()
        content.addLayout(result_actions)

        # ── Mode stack: By Game (index 0) | All Mods (index 1) ──────────
        self._mode_stack = QStackedWidget()

        # ── By-Game widget ────────────────────────────────────────────────
        by_game_widget = QWidget()
        by_game_layout = QVBoxLayout(by_game_widget)
        by_game_layout.setContentsMargins(0, 0, 0, 0)

        self._game_search = QLineEdit()
        self._game_search.setPlaceholderText("Search titles, serials, files, paths, regions, or CRCs…")
        self._game_search.setAccessibleName("Search library games")
        self._game_search.setClearButtonEnabled(True)
        self._game_search.setToolTip(
            "All words must match, even across different game fields. "
            "Matching ignores case and punctuation. Search does not scan your folders."
        )
        self._game_search_timer = QTimer(self)
        self._game_search_timer.setSingleShot(True)
        self._game_search_timer.setInterval(180)
        self._game_search_timer.timeout.connect(self._on_game_filters_changed)
        self._game_search.textChanged.connect(lambda: self._game_search_timer.start())
        by_game_layout.addWidget(self._game_search)

        filters = QHBoxLayout()
        self._game_filter = QComboBox()
        self._game_filter.setAccessibleName("Filter library games")
        for label, value in (
            ("All games", "all"), ("With installed mods", "with_mods"),
            ("Without installed mods", "without_mods"), ("Disc images only", "disc"),
            ("Tracked only (no disc)", "tracked"),
        ):
            self._game_filter.addItem(label, value)
        self._game_filter.currentIndexChanged.connect(self._on_game_filters_changed)
        filters.addWidget(self._game_filter, 1)
        self._game_sort = QComboBox()
        self._game_sort.setAccessibleName("Sort library games")
        for label, value in (
            ("Title A–Z", "title"), ("Title Z–A", "title_desc"),
            ("Most installed mods", "mods"), ("Largest disc images", "size"),
            ("Serial", "serial"),
        ):
            self._game_sort.addItem(label, value)
        self._game_sort.currentIndexChanged.connect(self._on_game_filters_changed)
        filters.addWidget(self._game_sort, 1)
        self._clear_game_filters_btn = QPushButton("Clear Filters")
        self._clear_game_filters_btn.clicked.connect(self._clear_game_filters)
        filters.addWidget(self._clear_game_filters_btn)
        by_game_layout.addLayout(filters)
        self._game_empty = QLabel()
        self._game_empty.setWordWrap(True)
        self._game_empty.setTextFormat(Qt.TextFormat.PlainText)
        self._game_empty.hide()
        by_game_layout.addWidget(self._game_empty)

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
        left_widget.setMinimumWidth(260)
        left_widget.setMaximumWidth(440)  # issue #32: wider so long game titles wrap nicely

        # Right: detail pane
        self._detail = _GameDetailPane(self.db)
        self._detail.enabled_requested.connect(self._run_mod_action)
        self._detail.browse_requested.connect(self.browse_game)

        self._splitter.addWidget(left_widget)
        self._splitter.addWidget(self._detail)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        by_game_layout.addWidget(self._splitter)
        self._mode_stack.addWidget(by_game_widget)

        # ── All-Mods widget ───────────────────────────────────────────────
        self._all_mods_pane = _AllModsPane(self.db, self.config)
        self._all_mods_pane.enabled_requested.connect(self._run_mod_action)
        self._mode_stack.addWidget(self._all_mods_pane)

        content.addWidget(self._mode_stack, 1)

        # Auto-detect unmanaged installed content before initial populate.
        self._sync_installed_content()

        # Initial populate (By Game mode)
        self._populate()
        self._restore_view_state()
        self._all_mods_pane._state_persistence_enabled = True
        self._state_persistence_enabled = True

    # ------------------------------------------------------------------
    # View mode switching
    # ------------------------------------------------------------------

    def _switch_to_by_game(self):
        self._by_game_btn.setChecked(True)
        self._all_mods_btn.setChecked(False)
        self._mode_stack.setCurrentIndex(0)
        self._populate()
        self._save_view_state("switching library view to by-game")

    def _switch_to_all_mods(self):
        self._by_game_btn.setChecked(False)
        self._all_mods_btn.setChecked(True)
        self._mode_stack.setCurrentIndex(1)
        self._all_mods_pane.config = self.config
        self._all_mods_pane.refresh()
        total = len(self.db.all())
        enabled = sum(1 for m in self.db.all() if m.enabled)
        self._count_lbl.setText(
            f"Tracked mods in library: {total} total  •  {enabled} enabled"
        )
        self._save_view_state("switching library view to all-mods")

    def _restore_view_state(self):
        state = _library_ui_state(self.config)
        self._restore_game_filter_state(state.get("by_game", {}))
        all_mods_state = state.get("all_mods", {})
        if isinstance(all_mods_state, dict):
            self._all_mods_pane.restore_filter_state(all_mods_state)

        mode = str(state.get("mode", "by_game") or "by_game")
        if mode == "all_mods":
            self._switch_to_all_mods()
        else:
            self._switch_to_by_game()

    def _save_view_state(self, context: str):
        if not getattr(self, "_state_persistence_enabled", False):
            return
        state = _library_ui_state(self.config)
        state["mode"] = "all_mods" if self._mode_stack.currentIndex() == 1 else "by_game"
        state["all_mods"] = self._all_mods_pane.current_filter_state()
        state["by_game"] = self._current_game_filter_state()
        selected_game = self._selected_game_state()
        if selected_game:
            state["selected_game"] = selected_game
        _save_library_config(self.config, context)

    def _current_game_filter_state(self) -> dict:
        return {
            "search": self._game_search.text(),
            "filter": self._game_filter.currentData(),
            "sort": self._game_sort.currentData(),
        }

    def _restore_game_filter_state(self, state):
        corrected = not isinstance(state, dict)
        state = state if isinstance(state, dict) else {}
        search = state.get("search", "")
        if not isinstance(search, str):
            search = ""
            corrected = True
        _block_signals(self._game_search, True)
        self._game_search.setText(search)
        _block_signals(self._game_search, False)
        for widget, key, default in (
            (self._game_filter, "filter", "all"), (self._game_sort, "sort", "title"),
        ):
            value = state.get(key, default)
            index = widget.findData(value) if isinstance(value, str) else -1
            if index < 0:
                index = 0
                corrected = True
            _block_signals(widget, True)
            widget.setCurrentIndex(index)
            _block_signals(widget, False)
        if corrected:
            logger.warning("Invalid saved Library game filters; restoring valid defaults")
            _library_ui_state(self.config)["by_game"] = self._current_game_filter_state()
            _save_library_config(self.config, "repairing Library game filters")

    def _on_game_filters_changed(self, *_args):
        self._game_search_timer.stop()
        if self._mode_stack.currentIndex() == 0:
            self._apply_game_filters()
        self._save_view_state("filtering Library games")

    def _clear_game_filters(self):
        self._game_search_timer.stop()
        for widget in (self._game_search, self._game_filter, self._game_sort):
            _block_signals(widget, True)
        self._game_search.clear()
        self._game_filter.setCurrentIndex(0)
        self._game_sort.setCurrentIndex(0)
        for widget in (self._game_search, self._game_filter, self._game_sort):
            _block_signals(widget, False)
        self._on_game_filters_changed()

    def _apply_game_filters(self):
        query = self._game_search.text().casefold()
        terms = [(word, "".join(ch for ch in word if ch.isalnum())) for word in query.split()]
        mode = self._game_filter.currentData()
        order = self._game_sort.currentData()

        def title_key(card):
            game = card.game
            return (
                (game.title or game.filename or game.serial).casefold(),
                game.serial.casefold(), game.path.casefold(),
            )

        ordered = sorted(self._cards, key=title_key, reverse=order == "title_desc")
        if order == "mods":
            ordered.sort(key=lambda card: -card.mod_count)
        elif order == "size":
            ordered.sort(key=lambda card: -card.game.size_bytes)
        elif order == "serial":
            ordered.sort(key=lambda card: (not bool(card.game.serial), card.game.serial.casefold()))
        self._shown_cards = []
        for card in self._cards:
            self._list_layout.removeWidget(card)
        for index, card in enumerate(ordered):
            visible = (
                (mode != "with_mods" or card.mod_count > 0)
                and (mode != "without_mods" or card.mod_count == 0)
                and (mode != "disc" or bool(card.game.path))
                and (mode != "tracked" or not card.game.path)
                and _game_matches_search(card.game, terms)
            )
            card.setVisible(visible)
            self._list_layout.insertWidget(index, card)
            if visible:
                self._shown_cards.append(card)
        if self._selected_card is not None and self._selected_card not in self._shown_cards:
            self._selected_card.set_selected(False)
            self._selected_card = None
            self._detail.clear_game()
        if self._selected_card is None:
            self._restore_selected_game()
        active = bool(terms) or mode != "all"
        self._clear_game_filters_btn.setEnabled(active or order != "title")
        if self._scan_active or self._scan_pending:
            message = (
                "No available games match yet; disc images are still loading. "
                "Use Clear Filters to show all available games."
            )
        else:
            message = "No games match these filters. Use Clear Filters to show all available games."
        self._game_empty.setText(message)
        self._game_empty.setVisible(active and not self._shown_cards)
        if self._cards or active:
            prefix = "Library games"
            if self._scan_active or self._scan_pending:
                prefix = "Scanning disc images"
            elif self._library_scan_error:
                prefix = "Scan failed"
            disc_count = sum(bool(card.game.path) for card in self._shown_cards)
            with_mods = sum(card.mod_count > 0 for card in self._shown_cards)
            self._count_lbl.setText(
                f"{prefix}: {len(self._shown_cards)}/{len(self._cards)} shown"
                f" • {with_mods} with installed mods\n"
                f"{disc_count} disc images • {len(self._shown_cards) - disc_count} tracked only"
            )

    def _selected_game_state(self) -> dict:
        card = getattr(self, "_selected_card", None)
        game = getattr(card, "game", None)
        if game is None:
            return {}
        path = str(getattr(game, "path", "") or "")
        serial = str(getattr(game, "serial", "") or "")
        title = str(getattr(game, "title", "") or "")
        if not any((path, serial, title)):
            return {}
        return {
            "path": path,
            "serial": serial.upper(),
            "title": title,
        }

    def _restore_selected_game(self) -> None:
        state = _library_ui_state(self.config)
        selected = state.get("selected_game", {})
        if not isinstance(selected, dict):
            logger.warning(
                "Saved library selected game state is invalid; clearing stale selection"
            )
            if state.pop("selected_game", None) is not None:
                _save_library_config(self.config, "clearing invalid selected game state")
            return

        target_path = str(selected.get("path", "") or "")
        target_serial = str(selected.get("serial", "") or "").upper()
        if not target_path and not target_serial:
            return

        # Prefer an exact disc-image path before falling back to another disc
        # for the same serial.
        candidates = sorted(
            self._cards,
            key=lambda card: str(getattr(card.game, "path", "") or "") != target_path,
        )
        hidden_match = False
        for card in candidates:
            game = getattr(card, "game", None)
            if game is None:
                continue
            game_path = str(getattr(game, "path", "") or "")
            game_serial = str(getattr(game, "serial", "") or "").upper()
            if target_path and game_path == target_path:
                if card not in self._shown_cards:
                    return
                card.set_selected(True)
                self._selected_card = card
                self._detail.show_game(game)
                return
            if (
                target_serial and game_serial == target_serial
                and not (target_path and (
                    self._scan_active or self._scan_pending or self._library_scan_error
                ))
            ):
                if card not in self._shown_cards:
                    hidden_match = True
                    continue
                card.set_selected(True)
                self._selected_card = card
                self._detail.show_game(game)
                return

        if hidden_match or self._scan_active or self._scan_pending or self._library_scan_error:
            return
        logger.warning(
            "Saved library selection path=%r serial=%r no longer matches a visible game; "
            "clearing stale selection",
            target_path,
            target_serial,
        )
        if state.pop("selected_game", None) is not None:
            _save_library_config(self.config, "clearing stale selected game state")

    # ------------------------------------------------------------------
    # Populate game list
    # ------------------------------------------------------------------

    def _populate(self):
        self._last_library_status = ""
        library_path = getattr(self.config, "game_library_path", "") or ""
        if library_path != self._scan_requested_path:
            self._invalidate_library_scan_cache()
        games = self._scan_library(library_path) if library_path else []
        pending = games is None
        self._update_scan_status()
        using_previous = (
            (pending or bool(self._library_scan_error))
            and self._rendered_library_path == library_path
        )
        if using_previous:
            games = [card.game for card in self._cards if card.game.path]
        if pending:
            self._last_library_status = "Scanning game library in the background…"
        elif self._library_scan_error:
            self._last_library_status = f"Could not scan game library folder: {library_path}"
            self.emit_status(self._last_library_status)

        # Clear current list
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()
        self._selected_card = None
        self._detail.clear_game()
        self._rendered_library_path = (
            library_path if using_previous or (not pending and not self._library_scan_error) else None
        )

        if not library_path:
            self._last_library_status = "Game library path not configured."
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
            self.emit_status(self._last_library_status)

            # Still show DB-tracked games even without a library path
            self._populate_db_games()
            self._apply_game_filters()
            return

        if pending and not using_previous:
            self._populate_db_games()
            self._count_lbl.setText(f"Scanning disc images • {len(self._cards)} tracked game(s) available")
            self._apply_game_filters()
            return

        if self._library_scan_error and not using_previous:
            msg = QLabel(
                "Could not scan your game library folder.\n\n"
                f"{self._library_scan_error}\n\n"
                "The mods installed in the database are still shown below.\n"
                "Check the folder in Settings or use Scan Library to try again."
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet("color: #b07070; font-size: 13px;")
            msg.setWordWrap(True)
            msg.setTextFormat(Qt.TextFormat.PlainText)
            self._list_layout.addWidget(msg)
            self._count_lbl.setText("Scan failed — showing installed mods only")
            self._populate_db_games()
            self._apply_game_filters()
            return

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
            self._apply_game_filters()
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
        db_only_games = self._get_db_only_games(library_serials, mods_by_serial)
        if db_only_games:
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
            f"Library games: {total} total  •  {games_with_mods} with installed mods"
        )
        self._apply_game_filters()

    def _invalidate_library_scan_cache(self) -> None:
        self._scan_generation += 1
        self._scan_requested_path = None
        self._scan_pending = None
        self._library_scan_cache_path = None
        self._library_scan_cache = []
        self._library_scan_error_path = None
        self._library_scan_error = ""

    def _scan_library(self, library_path: str) -> Optional[list[GameEntry]]:
        if self._library_scan_cache_path == library_path:
            return list(self._library_scan_cache)
        if self._library_scan_error_path == library_path:
            return []
        if self._scan_requested_path != library_path:
            self._scan_generation += 1
            self._scan_requested_path = library_path
            self._scan_pending = (self._scan_generation, library_path)
            self._start_next_scan()
            if self._library_scan_error_path == library_path:
                return []
        return None

    def _start_next_scan(self):
        if self._scan_active is not None or self._scan_pending is None:
            return
        import threading
        generation, path = self._scan_pending
        self._scan_pending = None
        self._scan_active = (generation, path)
        # A worker owns the relay independently of panel lifetime.
        result = _LibraryScanResult()
        result.finished.connect(self._on_library_scan_finished)

        def run():
            games, error = [], ""
            try:
                games = scan_library(path, strict=True)
            except Exception as exc:
                logger.warning("Could not scan game library folder %s: %s", path, exc)
                error = str(exc) or type(exc).__name__
            result.finished.emit(generation, path, games, error)
            result.deleteLater()

        try:
            threading.Thread(target=run, daemon=True).start()
        except RuntimeError as exc:
            logger.warning("Could not start game library scan: %s", exc)
            result.deleteLater()
            # Avoid re-entering list construction if thread creation fails.
            self._scan_active = None
            self._library_scan_error_path = path
            self._library_scan_error = str(exc) or type(exc).__name__

    @pyqtSlot(int, str, object, str)
    def _on_library_scan_finished(self, generation, path, games, error):
        if self._scan_active != (generation, path):
            return
        self._scan_active = None
        current_path = getattr(self.config, "game_library_path", "") or ""
        if current_path != self._scan_requested_path:
            self._invalidate_library_scan_cache()
            if current_path:
                self._scan_library(current_path)
        elif generation == self._scan_generation:
            if error:
                self._library_scan_error_path = path
                self._library_scan_error = error
            else:
                self._library_scan_cache_path = path
                self._library_scan_cache = list(games)
                self._library_scan_error_path = None
                self._library_scan_error = ""
        self._start_next_scan()
        self._update_scan_status()
        if self._mode_stack.currentIndex() == 0:
            self._populate()
        elif error and generation == self._scan_generation:
            self.emit_status("Game library scan failed; use Scan Library to retry.")

    def _update_scan_status(self):
        if self._library_scan_error:
            message = (
                f"Disc-image scan failed: {self._library_scan_error}\n"
                "Showing previous results for this folder when available, plus tracked mods. "
                "Check Settings and use Scan Library to retry."
            )
        elif self._scan_active or self._scan_pending:
            message = (
                "Scanning disc images in the background; you can use the library or switch views. "
                "Existing cards remain available while this folder refreshes."
            )
        else:
            message = ""
        self._scan_status.setText(message)
        self._scan_status.setVisible(bool(message))

    # ------------------------------------------------------------------
    # DB-game helpers
    # ------------------------------------------------------------------

    def _get_db_only_games(
        self,
        exclude_serials: set[str],
        serial_counts: Optional[dict[str, int]] = None,
    ) -> list[tuple[GameEntry, int]]:
        """Build GameEntry objects for serials in the mod DB that aren't in exclude_serials."""
        from src.core.game_registry import lookup_game_title
        if serial_counts is None:
            all_mods = self.db.all()
            serial_counts = {}
            for m in all_mods:
                if m.game_id:
                    key = m.game_id.upper()
                    serial_counts[key] = serial_counts.get(key, 0) + 1

        result: list[tuple[GameEntry, int]] = []
        for serial, mod_count in sorted(serial_counts.items()):
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
        for game, mod_count in db_only:
            card = _GameCard(game, mod_count, config=self.config)
            card.clicked.connect(self._on_game_clicked)
            self._list_layout.addWidget(card)
            self._cards.append(card)
        self._list_layout.addStretch()
        self._count_lbl.setText(f"Tracked games with installed mods: {len(db_only)}")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_game_clicked(self, game: GameEntry):
        card = next((card for card in self._shown_cards if card.game is game), None)
        if card is None:
            return
        # Deselect previous
        if self._selected_card:
            self._selected_card.set_selected(False)

        # Select new
        card.set_selected(True)
        self._selected_card = card

        self._detail.show_game(game)
        self._save_view_state("selecting game in library")

    def _on_mod_toggled(self):
        """Refresh the game list counts after a mod toggle."""
        if self._mode_stack.currentIndex() == 1:
            self._switch_to_all_mods()
            return
        self._save_view_state("refreshing library after mod toggle")
        self._populate()

    def _confirm_mod_action(self, states, scope, skipped=0):
        from src.core.pcsx2_layout import get_deploy_path
        mods = [self.db.get(mid) for mid in states]
        box = QMessageBox(self)
        box.setWindowTitle("Review Library Mod Action")
        box.setTextFormat(Qt.TextFormat.PlainText)
        changed = sum(mod.enabled != states[mod.id] for mod in mods)
        box.setText(
            f"Apply the requested state to {len(mods)} mod(s)?\nScope: {scope}\n"
            f"{changed} flag(s) will change; {len(mods) - changed} already match and will be reconciled again."
        )
        details = []
        for kind in dict.fromkeys(mod.mod_type for mod in mods):
            if kind == ModType.SAVE_FILE:
                details.append("Save files: library flags only; live memory cards are never copied or removed.")
            else:
                target = get_deploy_path(self.config, kind)
                details.append(f"{kind.value}: {target or 'No destination configured — check Settings, then retry.'}")
        box.setInformativeText(
            "Only the listed flags change. Affected destinations are rebuilt using all enabled mods, "
            "including other games and hidden results, to preserve priorities and shared files. "
            "Back up installed content first.\n\n"
            + "\n".join(details)
            + (f"\n{skipped} original mod(s) were removed and will be skipped." if skipped else "")
            + ("\nThis action replaces the earlier retry snapshot; it does not finish that earlier action."
               if self._mod_retry_states and self._mod_retry_states != states else "")
            + "\n\nShow Details lists every mod and requested state."
        )
        box.setDetailedText("\n".join(
            f"{mod.name} [{mod.id}] • {mod.mod_type.value} • "
            f"{'Enabled' if mod.enabled else 'Disabled'} → {'Enabled' if states[mod.id] else 'Disabled'}"
            for mod in mods
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _run_mod_action(self, states, scope, confirm=True, *, retry=False, skipped=0):
        if self._mod_action_busy:
            return
        states = {mid: enabled for mid, enabled in states.items() if self.db.get(mid) is not None}
        if not states:
            self.emit_status("No requested mods remain installed; no changes made.")
            return
        self._mod_action_busy = True
        self._mod_retry_btn.setEnabled(False)
        self._mod_dismiss_btn.setEnabled(False)
        attempted = False
        display_scope = f"Retry original action — {scope}" if retry else scope
        try:
            replacing = bool(self._mod_retry_states and self._mod_retry_states != states)
            if (confirm or replacing) and not self._confirm_mod_action(states, display_scope, skipped):
                self.emit_status("Library mod action cancelled; no changes made.")
                return
            # Keep requested states, not the inverse of possibly already-saved flags.
            self._mod_retry_states = dict(states)
            self._mod_retry_scope = scope
            attempted = True
            requested = "\n".join(
                f"{self.db.get(mid).name} [{mid}] → {'Enabled' if enabled else 'Disabled'}"
                for mid, enabled in states.items()
            )
            try:
                count, warnings = self.manager.set_enabled_many(states, self.config)
            except Exception as exc:
                logger.warning("Could not complete Library mod action (%s): %s", scope, exc)
                message = (
                    f"Library mod action could not finish: {exc or type(exc).__name__}\nScope: {display_scope}\n"
                    "Flags may already be saved, but installed files may be incomplete. "
                    "Correct the problem and use Retry Original Action; do not toggle again to retry."
                )
            else:
                message = f"Saved requested enabled flags for {len(states)} mod(s).\nScope: {display_scope}"
                if warnings:
                    message += "\n" + "\n".join(warnings) + "\nCorrect the problem and use Retry Original Action."
                else:
                    self._mod_retry_states = {}
                    if all(self.db.get(mid).mod_type == ModType.SAVE_FILE for mid in states):
                        message += "\nSave-file flags only; no live files were deployed or removed."
                    else:
                        message += f"\nDeployment reconciled ({count} item(s))."
                message += "\nLive memory-card files were not changed."
            message += "\n\nRequested states:\n" + requested
            if skipped:
                message += f"\nSkipped {skipped} original mod(s) that were removed."
            self._mod_feedback.setPlainText(message)
            self._mod_feedback.show()
            self._mod_dismiss_btn.show()
            self.emit_status(message.splitlines()[0])
        finally:
            self._mod_action_busy = False
            self._mod_retry_btn.setVisible(bool(self._mod_retry_states))
            self._mod_retry_btn.setEnabled(True)
            self._mod_dismiss_btn.setEnabled(True)
            if attempted:
                self._on_mod_toggled()

    def _retry_mod_action(self):
        if self._mod_action_busy or not self._mod_retry_states:
            return
        states = {mid: enabled for mid, enabled in self._mod_retry_states.items() if self.db.get(mid) is not None}
        if not states:
            self._mod_retry_states = {}
            self._mod_retry_btn.hide()
            self._mod_feedback.setPlainText("None of the original mods remain installed. No changes made.")
            return
        skipped = len(self._mod_retry_states) - len(states)
        self._run_mod_action(states, self._mod_retry_scope, True, retry=True, skipped=skipped)

    def _dismiss_mod_result(self):
        if self._mod_action_busy:
            return
        self._mod_retry_states = {}
        self._mod_retry_scope = ""
        self._mod_feedback.hide()
        self._mod_retry_btn.hide()
        self._mod_dismiss_btn.hide()

    def refresh(self):
        self._invalidate_library_scan_cache()
        self._sync_installed_content()
        if self._mode_stack.currentIndex() == 1:
            self._last_library_status = ""
            library_path = getattr(self.config, "game_library_path", "") or ""
            if library_path:
                self._scan_library(library_path)
            self._update_scan_status()
            self._switch_to_all_mods()
            self.emit_status("Library refreshed; disc-image scan runs in the background")
        else:
            self._populate()
            if not self._last_library_status:
                self.emit_status("Library refreshed")

    def _sync_installed_content(self):
        """Auto-import unmanaged installed content so it appears in the library."""
        imported = self.manager.auto_import_unmanaged_content(self.config)
        if imported > 0:
            self.emit_status(f"Detected and added {imported} installed item(s)")

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

    def _open_profiles_dialog(self):
        """Open the Mod Profiles management dialog."""
        from src.ui.widgets import ModProfilesDialog
        dlg = ModProfilesDialog(self.db, self.config, self)
        dlg.profile_applied.connect(self._on_profile_applied)
        dlg.exec()

    def _on_profile_applied(self, name: str):
        """Refresh the library after a profile is applied."""
        self.refresh()
        self.emit_status(f"Profile '{name}' processed — check the dialog for deployment details")
