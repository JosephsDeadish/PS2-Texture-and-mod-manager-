"""Generic mod management panel for texture packs, pnach, cover art, saves, cheats."""

import logging
import os
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from src.core.config_manager import save_config
from src.core.game_registry import serial_matches_query
from src.core.mod_manager import ModDatabase, ModManager
from src.models.mod import AppConfig, ModInfo, ModType
from src.ui.base_panel import BasePanel
from src.ui.import_dialog import EditModDialog, ImportModDialog
from src.ui.widgets import (
    ConflictDialog,
    EmptyStateWidget,
    ModDetailsDialog,
    ModItemWidget,
)

logger = logging.getLogger(__name__)


_TYPE_META = {
    ModType.TEXTURE_PACK: {
        "icon": "🎨",
        "label": "Texture Packs",
        "desc": "HD texture replacements for PS2 games",
        "ext_filter": "Archives (*.zip *.7z *.rar);;All Files (*)",
        "folder": True,
        "deploy_key": "textures_path",
    },
    ModType.PNACH: {
        "icon": "🔧",
        "label": "PNACH Codes & Cheats",
        "desc": "Game patches, widescreen cheats, and other code mods applied via PCSX2",
        "ext_filter": "PNACH Files (*.pnach);;All Files (*)",
        "folder": False,
        "deploy_key": "pnach_path",
    },
    ModType.COVER_ART: {
        "icon": "🖼️",
        "label": "Cover Art",
        "desc": "Game cover artwork displayed in the PCSX2 game list",
        "ext_filter": "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)",
        "folder": False,
        "deploy_key": "cover_art_path",
    },
    ModType.SAVE_FILE: {
        "icon": "💾",
        "label": "Save Files",
        "desc": "PS2 game save files (.ps2 / .mcd memory cards)",
        "ext_filter": "Save Files (*.ps2 *.mcd *.mc2 *.bin);;All Files (*)",
        "folder": False,
        "deploy_key": "memcards_path",
    },
    ModType.CHEAT: {
        "icon": "🔧",
        "label": "PNACH Codes & Cheats",
        "desc": "Game patches, widescreen cheats, and other code mods applied via PCSX2",
        "ext_filter": "PNACH Files (*.pnach);;All Files (*)",
        "folder": False,
        "deploy_key": "pnach_path",
    },
}


_STATUS_FILTERS = [
    ("All statuses", "all"),
    ("Enabled", "enabled"),
    ("Disabled", "disabled"),
    ("Conflicts", "conflicts"),
    ("Completely shadowed", "shadowed"),
    ("Code issues (enabled)", "code_issues"),
]


def _mod_matches_status(mod: ModInfo, status: str, issue_state: dict) -> bool:
    if status == "enabled":
        return mod.enabled
    if status == "disabled":
        return not mod.enabled
    if status == "conflicts":
        return mod.id in issue_state["conflicting_ids"]
    if status == "shadowed":
        return mod.id in issue_state["shadowed_ids"]
    if status == "code_issues":
        validation = issue_state["pnach_validation"].get(mod.id, {})
        return bool(validation.get("errors", 0) or validation.get("warnings", 0))
    return True


def _mod_panel_empty_message(
    label: str, query: str, author: str, library_only: bool, status: str = "all",
    has_mods: bool = True,
) -> str:
    active = []
    if query.strip():
        active.append(f"search {query!r}")
    if author:
        active.append(f"author {author!r}")
    if library_only:
        active.append("library-only filter")
    if status != "all":
        status_label = next((text for text, value in _STATUS_FILTERS if value == status), status)
        active.append(f"status {status_label!r}")
    if not has_mods or not active:
        return f"No {label} yet.\nClick ➕ Import to add some."
    return (
        f"No {label.lower()} match the current filters.\n"
        "Try clearing: " + ", ".join(active) + "."
    )


def _block_signals(widget, blocked: bool) -> None:
    setter = getattr(widget, "blockSignals", None)
    if callable(setter):
        setter(blocked)


def _mod_panel_state_bucket(config: AppConfig, mod_type: ModType) -> dict:
    ui_state = getattr(config, "ui_state", None)
    if not isinstance(ui_state, dict):
        ui_state = {}
        config.ui_state = ui_state
    mod_panels = ui_state.setdefault("mod_panels", {})
    if not isinstance(mod_panels, dict):
        mod_panels = {}
        ui_state["mod_panels"] = mod_panels
    panel_state = mod_panels.setdefault(mod_type.value, {})
    if not isinstance(panel_state, dict):
        panel_state = {}
        mod_panels[mod_type.value] = panel_state
    return panel_state


def _save_mod_panel_config(config: AppConfig, context: str) -> None:
    try:
        save_config(config)
    except Exception as exc:
        logger.warning("Could not save mod panel config after %s: %s", context, exc)


def _mod_matches_query(mod: ModInfo, query: object) -> bool:
    """Return True when *mod* matches the free-text search query."""
    if not isinstance(query, str):
        return False

    needle = query.strip().casefold()
    if not needle:
        return True

    compact = "".join(ch for ch in needle if ch.isalnum())

    def _matches_text(value: object) -> bool:
        if not isinstance(value, str):
            return False
        lowered = value.casefold()
        if needle in lowered:
            return True
        if compact:
            value_compact = "".join(ch for ch in lowered if ch.isalnum())
            if compact in value_compact:
                return True
        return False

    for value in (
        mod.id,
        mod.name,
        mod.author,
        mod.description,
        mod.game_id,
        mod.version,
        mod.source_url,
        mod.thumbnail_url,
        mod.path,
        getattr(mod.mod_type, "value", ""),
    ):
        if _matches_text(value):
            return True

    if any(_matches_text(tag) for tag in getattr(mod, "tags", []) if isinstance(tag, str)):
        return True
    if any(_matches_text(rel_path) for rel_path in getattr(mod, "files", []) if isinstance(rel_path, str)):
        return True

    if serial_matches_query(mod.game_id, query):
        return True

    return False


class ModPanel(BasePanel):
    """
    Unified panel for managing mods of a specific type.
    Shows a searchable, scrollable list of mod items with
    enable/disable toggles, priority controls, conflict detection,
    and import/deploy actions.
    """

    # Emitted when the user asks to view mods by an author in a *different* panel type.
    # Payload: (author: str, target_mod_type: ModType)
    navigate_to_author_type = pyqtSignal(str, object)

    def __init__(self, mod_type: ModType, db: ModDatabase, config: AppConfig,
                 extra_types: list = None, parent=None):
        meta = _TYPE_META[mod_type]
        super().__init__(
            f"{meta['icon']}  {meta['label']}",
            meta["desc"],
            parent=parent,
        )
        self.mod_type = mod_type
        self.extra_types: list = list(extra_types or [])
        self.db = db
        self.config = config
        self.manager = ModManager(db)
        self._state_persistence_enabled = False
        self._library_serials_cache_path = ""
        self._library_serials_cache = frozenset()
        self._issue_state_cache = None
        self._build()

    def _all_mods(self) -> list:
        """Return all mods for the primary type and any extra types, deduped by id."""
        seen: set = set()
        result = []
        for mt in [self.mod_type] + self.extra_types:
            for m in self.db.by_type(mt):
                if m.id not in seen:
                    seen.add(m.id)
                    result.append(m)
        return result


    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        content = self._content_layout

        # ---- Toolbar ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search…")
        self._search.setObjectName("search_bar")
        self._search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search, 1)

        # Sort
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Name ↑", "Name ↓", "Priority ↑", "Priority ↓", "Size"])
        self._sort_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self._sort_combo)

        # Import button
        import_btn = QPushButton("➕ Import")
        import_btn.setObjectName("primary_btn")
        import_btn.clicked.connect(self._import_mod)
        toolbar.addWidget(import_btn)

        # Conflicts button
        conflict_btn = QPushButton("⚠ Conflicts")
        conflict_btn.clicked.connect(self._show_conflicts)
        toolbar.addWidget(conflict_btn)

        # Check for Updates button
        updates_btn = QPushButton("🔔 Updates")
        updates_btn.setToolTip("Check for updates for mods that have a GitHub source URL")
        updates_btn.clicked.connect(self._check_updates)
        toolbar.addWidget(updates_btn)

        # PNACH Code Builder button — only visible on PNACH panel
        if self.mod_type == ModType.PNACH:
            builder_btn = QPushButton("🧩 Build from DB")
            builder_btn.setToolTip(
                "Open the PNACH Code Builder — select effects from the known-address\n"
                "database for your game and generate a merged .pnach file"
            )
            builder_btn.setObjectName("primary_btn")
            builder_btn.clicked.connect(self._open_code_builder)
            toolbar.addWidget(builder_btn)

        content.addLayout(toolbar)

        # ---- Author + library filter row ----
        author_row = QHBoxLayout()
        author_row.setSpacing(6)

        author_label = QLabel("👤 Author:")
        author_label.setStyleSheet("color: #7070a0; font-size: 12px;")
        author_row.addWidget(author_label)

        self._author_filter = QComboBox()
        self._author_filter.setMinimumWidth(160)
        self._author_filter.addItem("All Authors", "")
        self._author_filter.currentIndexChanged.connect(self._apply_filter)
        author_row.addWidget(self._author_filter)

        refresh_authors_btn = QPushButton("↺")
        refresh_authors_btn.setFixedWidth(28)
        refresh_authors_btn.setToolTip("Refresh author list")
        refresh_authors_btn.clicked.connect(self._refresh_author_filter)
        author_row.addWidget(refresh_authors_btn)

        # Game library filter — only show mods for games you own
        self._library_filter_check = QCheckBox("🎮 My Library Only")
        self._library_filter_check.setStyleSheet("color: #80b0ff; font-size: 12px;")
        self._library_filter_check.stateChanged.connect(self._apply_filter)
        author_row.addWidget(self._library_filter_check)

        self._status_filter = QComboBox()
        for label, value in _STATUS_FILTERS:
            if value == "shadowed" and self.mod_type != ModType.TEXTURE_PACK:
                continue
            if value == "code_issues" and not any(
                mt in (ModType.PNACH, ModType.CHEAT) for mt in [self.mod_type] + self.extra_types
            ):
                continue
            self._status_filter.addItem(label, value)
        self._status_filter.setAccessibleName("Filter mods by status")
        self._status_filter.setToolTip(
            "Narrow this list by enabled state or detected issues.\n"
            "Code checks cover enabled PNACH/cheat mods only.\n"
            "Enable All and Disable All still affect every mod in this panel."
        )
        self._status_filter.currentIndexChanged.connect(self._apply_filter)
        author_row.addWidget(self._status_filter)

        author_row.addStretch()
        content.addLayout(author_row)

        # ---- Enable-all / Disable-all ----
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("All mods in this panel:"))
        enable_all = QPushButton("✅ Enable All")
        enable_all.setObjectName("success_btn")
        enable_all.clicked.connect(self._enable_all)
        batch_row.addWidget(enable_all)
        disable_all = QPushButton("🚫 Disable All")
        disable_all.clicked.connect(self._disable_all)
        batch_row.addWidget(disable_all)
        batch_row.addStretch()

        clear_filters = QPushButton("✖ Clear Filters")
        clear_filters.setToolTip("Reset search, sort, author, library, and status filters")
        clear_filters.clicked.connect(self._clear_filters)
        batch_row.addWidget(clear_filters)

        # Status / conflict label — acts as a clickable link when conflicts exist
        # Issue #20: placed on its own row below the toolbar to avoid triggering a scrollbar
        self._count_lbl = QPushButton("")
        self._count_lbl.setFlat(True)
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 12px; text-align: left; border: none;")
        self._count_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self._count_lbl.clicked.connect(self._on_count_lbl_clicked)
        content.addLayout(batch_row)
        content.addWidget(self._count_lbl)

        # ---- PCSX2 guidance banner (texture / pnach / cheat panels only) ----
        if self.mod_type in (ModType.TEXTURE_PACK, ModType.PNACH, ModType.CHEAT):
            self._guidance_banner = self._make_guidance_banner()
            content.addWidget(self._guidance_banner)

        # ---- Scroll area for mod items ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_container)
        content.addWidget(self._scroll, 1)

        # Apply mode-aware tooltips to toolbar buttons (issue #31)
        self._apply_panel_tooltips(import_btn, conflict_btn, enable_all, disable_all)

        self._refresh_author_filter()
        self._restore_filter_state()
        self.refresh()
        self._state_persistence_enabled = True

    def _apply_panel_tooltips(
        self,
        import_btn: QPushButton,
        conflict_btn: QPushButton,
        enable_all: QPushButton,
        disable_all: QPushButton,
    ) -> None:
        """Set tooltip mode-aware tooltips on the panel toolbar buttons."""
        from src.ui.tooltips import get_tip as _tip
        _m = getattr(self.config, "tooltip_mode", "normal") if self.config else "normal"
        import_btn.setToolTip(_tip("import", _m))
        conflict_btn.setToolTip(_tip("conflicts", _m))
        enable_all.setToolTip(_tip("enable_all", _m))
        disable_all.setToolTip(_tip("disable_all", _m))
        if hasattr(self, "_library_filter_check"):
            self._library_filter_check.setToolTip(_tip("library_only", _m))

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        self._invalidate_library_serial_cache()
        self._invalidate_issue_state_cache()
        self._refresh_author_filter()
        self._apply_filter()

    def _invalidate_library_serial_cache(self) -> None:
        self._library_serials_cache_path = ""
        self._library_serials_cache = frozenset()

    def _invalidate_issue_state_cache(self) -> None:
        self._issue_state_cache = None

    def _issue_state(self) -> dict:
        cache = getattr(self, "_issue_state_cache", None)
        if isinstance(cache, dict):
            return cache

        conflicts = []
        for mt in [self.mod_type] + self.extra_types:
            try:
                conflicts.extend(self.manager.detect_conflicts(mt))
            except Exception as exc:
                logger.warning("Could not detect conflicts for %s: %s", mt.value, exc)

        pnach_conflicts = []
        for mt in [self.mod_type] + self.extra_types:
            if mt in (ModType.PNACH, ModType.CHEAT):
                try:
                    pnach_conflicts.extend(self.manager.detect_pnach_conflicts(mt))
                except Exception as exc:
                    logger.warning("Could not detect PNACH conflicts for %s: %s", mt.value, exc)

        conflicting_ids = set()
        for conflict in conflicts:
            conflicting_ids.add(conflict.mod_a_id)
            conflicting_ids.add(conflict.mod_b_id)
        for conflict in pnach_conflicts:
            conflicting_ids.update((conflict["mod_a_id"], conflict["mod_b_id"]))

        shadowed_ids: set = set()
        if self.mod_type == ModType.TEXTURE_PACK:
            try:
                shadowed_map = self.manager.detect_shadowed_mods(self.mod_type)
                shadowed_ids = set(shadowed_map.keys())
            except Exception as exc:
                logger.warning(
                    "Could not detect shadowed texture packs for %s: %s",
                    self.mod_type.value,
                    exc,
                )

        pnach_validation: dict = {}
        if any(mt in (ModType.PNACH, ModType.CHEAT) for mt in [self.mod_type] + self.extra_types):
            try:
                raw = self.manager.validate_all_pnach()
                for mid, issues in raw.items():
                    errors = sum(1 for iss in issues if iss.severity == "error")
                    warnings = sum(1 for iss in issues if iss.severity == "warning")
                    pnach_validation[mid] = {"errors": errors, "warnings": warnings}
            except Exception as exc:
                logger.warning("Could not validate PNACH status for %s: %s", self.mod_type.value, exc)

        cache = {
            "conflicts": conflicts,
            "pnach_conflicts": pnach_conflicts,
            "conflicting_ids": conflicting_ids,
            "shadowed_ids": shadowed_ids,
            "pnach_validation": pnach_validation,
        }
        self._issue_state_cache = cache
        return cache

    def _make_guidance_banner(self) -> QWidget:
        """Build a dismissable PCSX2 guidance banner for texture/pnach/cheat panels."""
        from src.core.pcsx2_layout import PCSX2_TEXTURES_HINT, PCSX2_CHEATS_HINT

        if self.mod_type == ModType.TEXTURE_PACK:
            hint = PCSX2_TEXTURES_HINT
            detail = (
                "Right-click the game → Properties → Graphics tab → "
                "tick <b>Load Textures</b>."
            )
        else:  # PNACH or CHEAT
            hint = PCSX2_CHEATS_HINT
            detail = (
                "Right-click the game → Properties → Patches tab → "
                "tick <b>Enable Cheats</b>."
            )

        banner = QFrame()
        banner.setObjectName("guidance_banner")
        banner.setStyleSheet(
            "QFrame#guidance_banner {"
            "  background: #1a2a1a; border: 1px solid #2a5a2a;"
            "  border-radius: 4px; margin: 2px 0;"
            "}"
        )
        row = QHBoxLayout(banner)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)

        icon_lbl = QLabel("ℹ️")
        icon_lbl.setFixedWidth(20)
        row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        short_lbl = QLabel(hint)
        short_lbl.setWordWrap(True)
        short_lbl.setStyleSheet("color: #90d090; font-size: 11px;")
        text_col.addWidget(short_lbl)
        detail_lbl = QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setStyleSheet("color: #60a060; font-size: 10px;")
        text_col.addWidget(detail_lbl)
        row.addLayout(text_col, 1)

        dismiss_btn = QPushButton("✕")
        dismiss_btn.setFixedSize(22, 22)
        dismiss_btn.setToolTip("Dismiss this hint")
        dismiss_btn.setAccessibleName("Dismiss hint")
        dismiss_btn.setAccessibleDescription("Hide this informational message")
        dismiss_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #60a060; "
            "border: none; font-size: 12px; }"
            "QPushButton:hover { color: #a0d0a0; }"
        )
        dismiss_btn.clicked.connect(banner.hide)
        row.addWidget(dismiss_btn)

        return banner

    def _refresh_author_filter(self):
        """Rebuild the author dropdown from the current mod list."""
        current = self._author_filter.currentData() or ""
        _block_signals(self._author_filter, True)
        self._author_filter.clear()
        self._author_filter.addItem("All Authors", "")

        authors = sorted(
            {m.author for m in self._all_mods() if m.author and m.author != "Unknown"},
        )
        for a in authors:
            # Mark favorite authors with a heart
            is_fav = (
                hasattr(self, "config")
                and self.config
                and a in getattr(self.config, "favorite_authors", [])
            )
            label = f"❤ {a}" if is_fav else a
            self._author_filter.addItem(label, a)

        # Restore previous selection
        idx = self._author_filter.findData(current)
        if idx >= 0:
            self._author_filter.setCurrentIndex(idx)
        _block_signals(self._author_filter, False)

    def _restore_filter_state(self):
        """Restore the saved search/sort/author/library filter state."""
        state = _mod_panel_state_bucket(self.config, self.mod_type)
        if not state:
            return

        should_save = False
        _block_signals(self._search, True)
        _block_signals(self._sort_combo, True)
        _block_signals(self._author_filter, True)
        _block_signals(self._library_filter_check, True)
        _block_signals(self._status_filter, True)
        try:
            query = str(state.get("query", ""))
            self._search.setText(query)
            state["query"] = query

            sort_idx = state.get("sort_index", 0)
            try:
                sort_idx = int(sort_idx)
            except (TypeError, ValueError):
                sort_idx = 0
            if 0 <= sort_idx < self._sort_combo.count():
                self._sort_combo.setCurrentIndex(sort_idx)
                state["sort_index"] = sort_idx
            else:
                logger.warning(
                    "Saved mod-panel sort index %r is no longer available; using the default sort order",
                    sort_idx,
                )
                self._sort_combo.setCurrentIndex(0)
                state["sort_index"] = 0
                should_save = True

            author = str(state.get("author", "") or "")
            if author:
                idx = self._author_filter.findData(author)
                if idx >= 0:
                    self._author_filter.setCurrentIndex(idx)
                    state["author"] = author
                else:
                    logger.warning(
                        "Saved mod-panel author filter %r is no longer available; using All Authors",
                        author,
                    )
                    self._author_filter.setCurrentIndex(0)
                    state["author"] = ""
                    should_save = True
            else:
                self._author_filter.setCurrentIndex(0)
                state["author"] = ""

            library_only = bool(state.get("library_only", False))
            self._library_filter_check.setChecked(library_only)
            state["library_only"] = library_only

            status = state.get("status", "all")
            status_idx = self._status_filter.findData(status)
            if status_idx < 0:
                logger.warning(
                    "Saved mod-panel status filter %r is no longer available; using All statuses",
                    status,
                )
                status_idx = 0
                should_save = True
            self._status_filter.setCurrentIndex(status_idx)
            state["status"] = self._status_filter.currentData() or "all"
        finally:
            _block_signals(self._search, False)
            _block_signals(self._sort_combo, False)
            _block_signals(self._author_filter, False)
            _block_signals(self._library_filter_check, False)
            _block_signals(self._status_filter, False)

        if should_save:
            _save_mod_panel_config(self.config, "sanitizing mod panel filter state")

    def _save_filter_state(self, context: str):
        if not getattr(self, "_state_persistence_enabled", False):
            return
        state = _mod_panel_state_bucket(self.config, self.mod_type)
        state.update({
            "query": self._search.text(),
            "sort_index": self._sort_combo.currentIndex(),
            "author": self._author_filter.currentData() or "",
            "library_only": self._library_filter_check.isChecked(),
            "status": self._status_filter.currentData() or "all",
        })
        _save_mod_panel_config(self.config, context)

    def _apply_filter(self):
        query = self._search.text().lower()
        author_filter = self._author_filter.currentData() or ""
        library_only = self._library_filter_check.isChecked()
        all_mods = self._all_mods()
        mods = all_mods
        status_filter = self._status_filter.currentData() or "all"
        sort_idx = self._sort_combo.currentIndex()

        if query:
            mods = [m for m in mods if _mod_matches_query(m, query)]

        if author_filter:
            mods = [m for m in mods if m.author == author_filter]

        if library_only:
            lib_serials = self._get_library_serials()
            if lib_serials:
                mods = [
                    m for m in mods
                    if m.game_id and m.game_id.upper() in lib_serials
                ]
            # If library is empty / unset, show nothing to avoid confusion
            else:
                mods = []

        sort_keys = [
            lambda m: m.name.lower(),
            lambda m: m.name.lower(),
            lambda m: m.priority,
            lambda m: m.priority,
            lambda m: m.size_bytes,
        ]
        reverse = [False, True, False, True, True]
        mods = sorted(mods, key=sort_keys[sort_idx], reverse=reverse[sort_idx])

        issue_state = self._issue_state()
        conflicts = issue_state["conflicts"]
        conflicting_ids = issue_state["conflicting_ids"]
        shadowed_ids = issue_state["shadowed_ids"]
        pnach_validation = issue_state["pnach_validation"]
        mods = [m for m in mods if _mod_matches_status(m, status_filter, issue_state)]

        # Clear existing items (leave the trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not mods:
            empty = EmptyStateWidget(
                _TYPE_META[self.mod_type]["icon"],
                _mod_panel_empty_message(
                    _TYPE_META[self.mod_type]["label"],
                    query,
                    author_filter,
                    library_only,
                    status_filter,
                    has_mods=bool(all_mods),
                ),
            )
            action = QPushButton("✖ Clear Filters" if all_mods else "➕ Import")
            action.setObjectName("primary_btn")
            action.clicked.connect(self._clear_filters if all_mods else self._import_mod)
            empty.layout().addWidget(action)
            self._list_layout.insertWidget(0, empty)
        else:
            for i, mod in enumerate(mods):
                v = pnach_validation.get(mod.id, {})
                tip_mode = getattr(self.config, "tooltip_mode", "normal") if self.config else "normal"
                widget = ModItemWidget(
                    mod,
                    has_conflict=(mod.id in conflicting_ids),
                    is_shadowed=(mod.id in shadowed_ids),
                    validation_errors=v.get("errors", 0),
                    validation_warnings=v.get("warnings", 0),
                    tooltip_mode=tip_mode,
                )
                widget.toggled.connect(self._on_toggle)
                widget.remove_requested.connect(self._on_remove)
                widget.priority_up.connect(self._on_priority_up)
                widget.priority_down.connect(self._on_priority_down)
                widget.details_requested.connect(self._on_details)
                widget.edit_requested.connect(self._on_edit)
                widget.filter_by_author.connect(self._filter_by_author)
                widget.conflicts_requested.connect(self._show_conflicts)
                self._list_layout.insertWidget(i, widget)

        enabled_count = sum(1 for m in all_mods if m.enabled)
        total_count = len(all_mods)
        panel_validation = [pnach_validation[m.id] for m in all_mods if m.id in pnach_validation]
        invalid_mods = sum(1 for v in panel_validation if v.get("errors", 0))
        warning_mods = sum(1 for v in panel_validation if v.get("warnings", 0) and not v.get("errors", 0))
        pnach_conflicts = issue_state["pnach_conflicts"]
        has_conflicts = bool(conflicts or pnach_conflicts)
        has_any_issue = bool(has_conflicts or shadowed_ids or invalid_mods or warning_mods)
        # Issue #4: clarify what the count refers to using the panel's mod type label
        type_label = _TYPE_META[self.mod_type].get("label", "mod(s)")
        status = f"Showing {len(mods)} of {total_count} {type_label}  •  {enabled_count} enabled"
        issue_notes = []
        if conflicts:
            issue_notes.append(f"{len(conflicts)} file conflict pair(s)")
        if pnach_conflicts:
            issue_notes.append(f"{len(pnach_conflicts)} PNACH address overlap(s)")
        if shadowed_ids:
            issue_notes.append(f"{len(shadowed_ids)} shadowed")
        if invalid_mods:
            issue_notes.append(f"{invalid_mods} invalid")
        if warning_mods:
            issue_notes.append(f"{warning_mods} with code warnings")
        if has_conflicts:
            issue_notes.append("Click to review conflicts")
        if issue_notes:
            status += "\n" + "  •  ".join(issue_notes)
        self._count_lbl.setText(status)
        self._count_lbl.setToolTip(
            "Counts cover every mod in this panel, including hidden results.\n"
            "Click to review file and PNACH address conflicts."
            if has_conflicts else
            "Counts cover every mod in this panel, including hidden results.\n"
            "Use the status filter to find shadowed mods or code issues."
        )
        self._count_lbl.setCursor(
            Qt.CursorShape.PointingHandCursor if has_conflicts else Qt.CursorShape.ArrowCursor
        )
        self._count_lbl.setStyleSheet(
            "color: #ff8080; font-size: 12px; text-align: left; border: none;"
            if has_any_issue else
            "color: #7070a0; font-size: 12px; text-align: left; border: none;"
        )
        self._save_filter_state("updating mod panel filters")

    def _clear_filters(self):
        """Reset the mod search, sort, author, library-only, and status filters."""
        for widget in (self._search, self._sort_combo, self._author_filter,
                       self._library_filter_check, self._status_filter):
            _block_signals(widget, True)

        self._search.clear()
        self._sort_combo.setCurrentIndex(0)
        self._author_filter.setCurrentIndex(0)
        self._library_filter_check.setChecked(False)
        self._status_filter.setCurrentIndex(0)

        for widget in (self._search, self._sort_combo, self._author_filter,
                       self._library_filter_check, self._status_filter):
            _block_signals(widget, False)

        self._save_filter_state("clearing mod panel filters")
        self._apply_filter()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_toggle(self, mod_id: str, enabled: bool):
        mod = self.db.get(mod_id)
        name = mod.name if mod else mod_id
        action = "Enabled" if enabled else "Disabled"

        # set_enabled always deploys/undeploys immediately
        count, warnings = self.manager.set_enabled(mod_id, enabled, self.config)

        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")

        if target_path:
            if warnings:
                self.emit_status(
                    f"{action} '{name}' — deployed with {len(warnings)} warning(s)"
                )
            else:
                self.emit_status(
                    f"{action} '{name}' — deployed {count} {meta['label'].lower()} to PCSX2"
                )
        else:
            self.emit_status(
                f"{action} '{name}' (configure PCSX2 path in Settings to auto-deploy)"
            )

        # Cover art: warn if multiple art enabled for same game serial
        if enabled and self.mod_type == ModType.COVER_ART:
            self._check_cover_art_duplicates(mod_id)

        self._invalidate_issue_state_cache()
        self._apply_filter()

    def _check_cover_art_duplicates(self, newly_enabled_id: str):
        """
        For Cover Art: warn when more than one cover art is enabled for the
        same game serial, and offer to automatically disable the others.
        """
        conflicts = self.manager.detect_cover_art_conflicts()
        if not conflicts:
            return

        for serial, mods in conflicts:
            ids_in_conflict = [m.id for m in mods]
            if newly_enabled_id not in ids_in_conflict:
                continue

            others = [m for m in mods if m.id != newly_enabled_id]
            other_names = ", ".join(f"'{m.name}'" for m in others)
            reply = QMessageBox.warning(
                self,
                "Multiple Cover Arts for Same Game",
                f"<b>{serial}</b> already has cover art enabled:<br>{other_names}<br><br>"
                "PCSX2 can only use one cover art per game. "
                "Would you like to automatically disable the other(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                for m in others:
                    self.manager.set_enabled(m.id, False)
                self.emit_status(
                    f"Disabled {len(others)} duplicate cover art(s) for {serial}"
                )

    def _on_remove(self, mod_id: str):
        mod = self.db.get(mod_id)
        if not mod:
            return
        reply = QMessageBox.question(
            self,
            "Remove Mod",
            f"Remove '{mod.name}'?\nThis will also delete its files from mod storage.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.manager.remove_mod(mod_id)
            self.emit_status(f"Removed '{mod.name}'")
            self._invalidate_issue_state_cache()
            self._apply_filter()

    def _on_priority_up(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod:
            self.manager.set_priority(mod_id, mod.priority + 1)
            self._invalidate_issue_state_cache()
            self._apply_filter()

    def _on_priority_down(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod and mod.priority > 0:
            self.manager.set_priority(mod_id, mod.priority - 1)
            self._invalidate_issue_state_cache()
            self._apply_filter()

    def _on_details(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod:
            dlg = ModDetailsDialog(mod, self)
            dlg.see_more_by_author.connect(self._on_see_more_by_author)
            dlg.edit_requested.connect(self._on_edit)
            dlg.exec()

    def _on_see_more_by_author(self, author: str, target_type: object):
        """
        Called when the user clicks "See more by [author]" in the details dialog.
        If *target_type* matches the current panel's mod type, filter in-panel.
        Otherwise emit navigate_to_author_type so MainWindow can switch panels.
        """
        if target_type == self.mod_type:
            self._filter_by_author(author)
        else:
            self.navigate_to_author_type.emit(author, target_type)

    def _get_library_serials(self) -> frozenset:
        """Return the set of game serials detected in the configured game library.

        Returns an empty frozenset if no library path is configured or no
        disc images with recognisable serials are found.
        """
        path = getattr(self.config, "game_library_path", "")
        if not path:
            self._invalidate_library_serial_cache()
            return frozenset()
        if (
            getattr(self, "_library_serials_cache_path", "") == path
            and isinstance(getattr(self, "_library_serials_cache", None), frozenset)
        ):
            return self._library_serials_cache
        try:
            from src.core.game_library import get_library_serials
            serials = get_library_serials(path)
        except Exception as exc:
            logger.warning("Could not load library serials for mod panel: %s", exc)
            serials = frozenset()
        self._library_serials_cache_path = path
        self._library_serials_cache = serials
        return serials

    def _filter_by_author(self, author: str):
        """Set the author filter dropdown to *author* and refresh the list."""
        idx = self._author_filter.findData(author)
        if idx >= 0:
            self._author_filter.setCurrentIndex(idx)
        else:
            # Author not yet in dropdown (e.g. after new import) — refresh first
            self._refresh_author_filter()
            idx = self._author_filter.findData(author)
            if idx >= 0:
                self._author_filter.setCurrentIndex(idx)
        self.emit_status(f"Showing mods by {author}")

    def _on_edit(self, mod_id: str):
        mod = self.db.get(mod_id)
        if not mod:
            return
        def save_metadata(meta):
            if self.db.get(mod_id) is None:
                raise ValueError("This mod is no longer installed.")
            self.manager.update_metadata(mod_id, **meta, fetch_thumbnail=False)

        dlg = EditModDialog(mod, self, save_callback=save_metadata)
        if dlg.exec() == dlg.DialogCode.Accepted:
            meta = dlg.updated_meta
            self.emit_status(f"Updated '{meta.get('name', mod.name)}'")
            self._refresh_author_filter()
            self._invalidate_issue_state_cache()
            self._apply_filter()

    def _enable_all(self):
        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")
        all_types = [self.mod_type] + self.extra_types
        pending = [mod for mod in self._all_mods() if not mod.enabled]
        if not pending:
            self.emit_status(f"All {meta['label'].lower()} are already enabled")
            return

        reply = QMessageBox.question(
            self,
            f"Enable All {meta['label']}",
            (
                f"Enable all {len(pending)} disabled {meta['label'].lower()}?\n\n"
                "They will be deployed to PCSX2 immediately."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.emit_status(f"Enable all {meta['label'].lower()} cancelled")
            return

        self.emit_status(f"Enabling {len(pending)} {meta['label'].lower()}…")
        for mod in pending:
            mod.enabled = True
            self.db.update(mod)
        # Single bulk deploy after all flags are set
        if target_path:
            total = sum(self.manager.deploy(mt, target_path)[0] for mt in all_types)
            self.emit_status(
                f"Enabled {len(pending)} {meta['label'].lower()} — deployed {total} to PCSX2"
            )
        else:
            self.emit_status(
                f"Enabled {len(pending)} {meta['label'].lower()} "
                "(configure path in Settings to deploy)"
            )
        self._invalidate_issue_state_cache()
        self._apply_filter()

    def _disable_all(self):
        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")
        all_types = [self.mod_type] + self.extra_types
        pending = [mod for mod in self._all_mods() if mod.enabled]
        if not pending:
            self.emit_status(f"No {meta['label'].lower()} are currently enabled")
            return

        reply = QMessageBox.question(
            self,
            f"Disable All {meta['label']}",
            (
                f"Disable all {len(pending)} enabled {meta['label'].lower()}?\n\n"
                "They will be removed from PCSX2 immediately."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.emit_status(f"Disable all {meta['label'].lower()} cancelled")
            return

        self.emit_status(f"Disabling {len(pending)} {meta['label'].lower()}…")
        for mod in pending:
            mod.enabled = False
            self.db.update(mod)
        # Re-deploy (nothing enabled → clears deployed files via empty deploy)
        if target_path:
            for mt in all_types:
                self.manager.deploy(mt, target_path)
            self.emit_status(
                f"Disabled {len(pending)} {meta['label'].lower()} — removed from PCSX2"
            )
        else:
            self.emit_status(f"Disabled {len(pending)} {meta['label'].lower()}")
        self._invalidate_issue_state_cache()
        self._apply_filter()

    def _on_count_lbl_clicked(self):
        """Click handler for the status/count label — opens conflict resolver if issues exist."""
        issues = self._issue_state()
        if issues["conflicts"] or issues["pnach_conflicts"]:
            self._show_conflicts()

    def _show_conflicts(self):
        issue_state = self._issue_state()
        conflicts = list(issue_state["conflicts"])
        pnach_conflicts = list(issue_state["pnach_conflicts"])

        if not conflicts and not pnach_conflicts:
            QMessageBox.information(
                self, "No Conflicts", "No conflicts detected between enabled mods! ✅"
            )
            return
        dlg = ConflictDialog(conflicts, self.db, self, pnach_conflicts=pnach_conflicts)
        dlg.exec()
        self._invalidate_issue_state_cache()
        self._apply_filter()

    def _open_code_builder(self):
        """Open the PNACH Code Builder dialog for the current game context."""
        from src.ui.widgets import PnachCodeBuilderDialog
        from src.core.config_manager import AppConfig

        # Try to determine cheats dir from config
        cheats_dir = ""
        try:
            cfg = AppConfig.load()
            pcsx2_root = cfg.pcsx2_path or ""
            if pcsx2_root:
                from src.core.pcsx2_layout import detect_pcsx2_subfolders
                paths = detect_pcsx2_subfolders(pcsx2_root)
                cheats_dir = paths.get("pnach_path", "")
        except Exception as exc:
            logger.warning("Could not determine cheats folder for PNACH code builder: %s", exc)

        # Try to pre-fill the game serial from the current library filter
        serial = ""
        try:
            if hasattr(self, '_library_filter_check') and self._library_filter_check.isChecked():
                # Get currently shown mods and infer serial from them
                mods = self.manager.list_mods(self.mod_type)
                enabled_serials = {m.game_id for m in mods if m.enabled and m.game_id}
                if len(enabled_serials) == 1:
                    serial = enabled_serials.pop()
        except Exception as exc:
            logger.warning("Could not infer current game serial for PNACH code builder: %s", exc)

        dlg = PnachCodeBuilderDialog(
            game_serial=serial,
            cheats_dir=cheats_dir,
            config=self.config,
            parent=self,
        )
        dlg.exec()
        self._invalidate_issue_state_cache()
        self._apply_filter()

    def _check_updates(self):
        """
        Run the update checker for all mods in this panel that have a source URL.
        Results are shown in a summary dialog; mods with available updates get an
        "↑ Update" badge and the list is refreshed.
        """
        from src.core.updater import UpdateChecker

        mods_with_source = [
            m for m in self._all_mods()
            if m.source_url
        ]
        if not mods_with_source:
            QMessageBox.information(
                self,
                "No Checkable Mods",
                "None of the mods in this panel have a source URL set.\n\n"
                "Add a GitHub Releases URL in a mod's Edit dialog to enable update checking."
            )
            return

        self.emit_status("Checking for updates…")

        # We collect results; since this is a background thread we accumulate
        # and show a dialog when done.
        results: list = []

        def _on_result(mod_id: str, has_update: bool):
            mod = self.db.get(mod_id)
            if mod:
                results.append((mod.name, has_update))

        def _on_complete(updates_found: int):
            from PyQt6.QtCore import QTimer
            def _show():
                self._apply_filter()
                if updates_found == 0:
                    QMessageBox.information(
                        self, "Up to Date",
                        f"✅ All {len(mods_with_source)} checked mod(s) are up to date."
                    )
                else:
                    update_names = "\n".join(
                        f"  • {name}" for name, upd in results if upd
                    )
                    QMessageBox.information(
                        self, "Updates Available",
                        f"🔔 {updates_found} update(s) available:\n\n{update_names}\n\n"
                        "Mods with available updates are marked with '↑ Update'.\n"
                        "To update, remove the mod and re-import the new version, "
                        "or use 'Download from URL' in the Browse panel."
                    )
                self.emit_status(
                    f"Update check complete — {updates_found} update(s) available"
                )
            QTimer.singleShot(0, _show)

        # Use a temporarily-scoped db view for just this panel's mods
        class _ScopedDB:
            """Minimal DB wrapper that only returns mods in the current panel."""
            def __init__(self, db, mod_ids):
                self._db = db
                self._ids = set(mod_ids)
            def all(self):
                return [m for m in self._db.all() if m.id in self._ids]
            def update(self, mod):
                return self._db.update(mod)

        scoped_db = _ScopedDB(self.db, [m.id for m in mods_with_source])
        checker = UpdateChecker(scoped_db)
        checker.start(on_result=_on_result, on_complete=_on_complete)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _import_mod(self):
        storage = self.config.mods_storage_path
        if not storage:
            QMessageBox.warning(
                self,
                "Storage Not Configured",
                "Please configure a Mod Storage folder in Settings first.",
            )
            return

        dlg = ImportModDialog(self.mod_type, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        path = dlg.source_path
        meta = dlg.meta

        try:
            mod = self.manager.install_from_folder(
                source_path=path,
                mod_type=self.mod_type,
                dest_base=storage,
                name=meta.get("name", ""),
                author=meta.get("author", ""),
                version=meta.get("version", ""),
                description=meta.get("description", ""),
                game_id=meta.get("game_id", ""),
                source_url=meta.get("source_url", ""),
            )
            # Mod is enabled by default — deploy it immediately
            type_meta = _TYPE_META[self.mod_type]
            target_path = getattr(self.config, type_meta["deploy_key"], "")
            if target_path:
                count, warnings = self.manager.deploy(self.mod_type, target_path)
                self.emit_status(f"Imported '{mod.name}' — deployed {count} to PCSX2")
            else:
                self.emit_status(
                    f"Imported '{mod.name}' (configure PCSX2 path in Settings to deploy)"
                )
            self._invalidate_issue_state_cache()
            self._apply_filter()
        except Exception as exc:
            logger.warning("Could not import mod in mod panel: %s", exc)
            QMessageBox.critical(self, "Import Error", str(exc))
