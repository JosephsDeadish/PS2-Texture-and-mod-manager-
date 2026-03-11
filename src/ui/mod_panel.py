"""Generic mod management panel for texture packs, pnach, cover art, saves, cheats."""

import os
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
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
        "label": "PNACH Patches",
        "desc": "Game patches and cheats applied at runtime",
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
        "icon": "⚡",
        "label": "Cheats (WS)",
        "desc": "Widescreen and other cheat patches",
        "ext_filter": "Cheat Files (*.pnach *.txt);;All Files (*)",
        "folder": False,
        "deploy_key": "cheats_path",
    },
}


class ModPanel(BasePanel):
    """
    Unified panel for managing mods of a specific type.
    Shows a searchable, scrollable list of mod items with
    enable/disable toggles, priority controls, conflict detection,
    and import/deploy actions.
    """

    def __init__(self, mod_type: ModType, db: ModDatabase, config: AppConfig, parent=None):
        meta = _TYPE_META[mod_type]
        super().__init__(
            f"{meta['icon']}  {meta['label']}",
            meta["desc"],
            parent=parent,
        )
        self.mod_type = mod_type
        self.db = db
        self.config = config
        self.manager = ModManager(db)
        self._build()

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

        # Deploy button
        deploy_btn = QPushButton("🚀 Deploy")
        deploy_btn.setToolTip("Copy enabled mods to PCSX2 folder")
        deploy_btn.clicked.connect(self._deploy)
        toolbar.addWidget(deploy_btn)

        # Conflicts button
        conflict_btn = QPushButton("⚠ Conflicts")
        conflict_btn.clicked.connect(self._show_conflicts)
        toolbar.addWidget(conflict_btn)

        content.addLayout(toolbar)

        # ---- Author filter row ----
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

        author_row.addStretch()

        # ---- Enable-all / Disable-all ----
        enable_all = QPushButton("✅ Enable All")
        enable_all.setObjectName("success_btn")
        enable_all.clicked.connect(self._enable_all)
        author_row.addWidget(enable_all)
        disable_all = QPushButton("🚫 Disable All")
        disable_all.clicked.connect(self._disable_all)
        author_row.addWidget(disable_all)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        author_row.addWidget(self._count_lbl)
        content.addLayout(author_row)

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

        self._refresh_author_filter()
        self.refresh()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        self._refresh_author_filter()
        self._apply_filter()

    def _refresh_author_filter(self):
        """Rebuild the author dropdown from the current mod list."""
        current = self._author_filter.currentData() or ""
        self._author_filter.blockSignals(True)
        self._author_filter.clear()
        self._author_filter.addItem("All Authors", "")

        authors = sorted(
            {m.author for m in self.db.by_type(self.mod_type) if m.author and m.author != "Unknown"},
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
        self._author_filter.blockSignals(False)

    def _apply_filter(self):
        query = self._search.text().lower()
        author_filter = self._author_filter.currentData() or ""
        mods = self.db.by_type(self.mod_type)
        sort_idx = self._sort_combo.currentIndex()

        if query:
            mods = [
                m for m in mods
                if query in m.name.lower()
                or (m.author and query in m.author.lower())
                or (m.game_id and query in m.game_id.lower())
                or (m.description and query in m.description.lower())
            ]

        if author_filter:
            mods = [m for m in mods if m.author == author_filter]

        sort_keys = [
            lambda m: m.name.lower(),
            lambda m: m.name.lower(),
            lambda m: m.priority,
            lambda m: m.priority,
            lambda m: m.size_bytes,
        ]
        reverse = [False, True, False, True, True]
        mods = sorted(mods, key=sort_keys[sort_idx], reverse=reverse[sort_idx])

        # Conflict info
        conflicts = self.manager.detect_conflicts(self.mod_type)
        conflicting_ids = set()
        for c in conflicts:
            conflicting_ids.add(c.mod_a_id)
            conflicting_ids.add(c.mod_b_id)

        # Clear existing items (leave the trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not mods:
            empty = EmptyStateWidget(
                _TYPE_META[self.mod_type]["icon"],
                f"No {_TYPE_META[self.mod_type]['label']} yet.\nClick ➕ Import to add some."
            )
            self._list_layout.insertWidget(0, empty)
        else:
            for i, mod in enumerate(mods):
                widget = ModItemWidget(mod, has_conflict=(mod.id in conflicting_ids))
                widget.toggled.connect(self._on_toggle)
                widget.remove_requested.connect(self._on_remove)
                widget.priority_up.connect(self._on_priority_up)
                widget.priority_down.connect(self._on_priority_down)
                widget.details_requested.connect(self._on_details)
                widget.edit_requested.connect(self._on_edit)
                self._list_layout.insertWidget(i, widget)

        enabled_count = sum(1 for m in self.db.by_type(self.mod_type) if m.enabled)
        total_count = len(self.db.by_type(self.mod_type))
        self._count_lbl.setText(
            f"{enabled_count}/{total_count} enabled"
            + (f"  •  {len(conflicts)} conflict(s)" if conflicts else "")
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_toggle(self, mod_id: str, enabled: bool):
        self.manager.set_enabled(mod_id, enabled)
        mod = self.db.get(mod_id)
        status = "enabled" if enabled else "disabled"
        self.emit_status(f"'{mod.name if mod else mod_id}' {status}")
        self._apply_filter()

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
            self._apply_filter()

    def _on_priority_up(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod:
            self.manager.set_priority(mod_id, mod.priority + 1)
            self._apply_filter()

    def _on_priority_down(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod and mod.priority > 0:
            self.manager.set_priority(mod_id, mod.priority - 1)
            self._apply_filter()

    def _on_details(self, mod_id: str):
        mod = self.db.get(mod_id)
        if mod:
            dlg = ModDetailsDialog(mod, self)
            dlg.exec()

    def _on_edit(self, mod_id: str):
        mod = self.db.get(mod_id)
        if not mod:
            return
        dlg = EditModDialog(mod, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            meta = dlg.updated_meta
            self.manager.update_metadata(
                mod_id,
                name=meta.get("name", ""),
                author=meta.get("author", ""),
                description=meta.get("description", ""),
                game_id=meta.get("game_id", ""),
                version=meta.get("version", ""),
                source_url=meta.get("source_url", ""),
                tags=meta.get("tags"),
            )
            # Apply thumbnail if explicitly fetched in dialog
            if meta.get("thumbnail_path"):
                updated = self.db.get(mod_id)
                if updated:
                    updated.thumbnail_path = meta["thumbnail_path"]
                    self.db.update(updated)
            self.emit_status(f"Updated '{meta.get('name', mod.name)}'")
            self._apply_filter()

    def _enable_all(self):
        for mod in self.db.by_type(self.mod_type):
            self.manager.set_enabled(mod.id, True)
        self.emit_status("All mods enabled")
        self._apply_filter()

    def _disable_all(self):
        for mod in self.db.by_type(self.mod_type):
            self.manager.set_enabled(mod.id, False)
        self.emit_status("All mods disabled")
        self._apply_filter()

    def _show_conflicts(self):
        conflicts = self.manager.detect_conflicts(self.mod_type)
        if not conflicts:
            QMessageBox.information(
                self, "No Conflicts", "No conflicts detected between enabled mods! ✅"
            )
            return
        dlg = ConflictDialog(conflicts, self.db, self)
        dlg.exec()
        self._apply_filter()

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
            # version is now passed directly to install_from_folder
            self.emit_status(f"Imported '{mod.name}'")
            self._apply_filter()
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    def _deploy(self):
        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")
        if not target_path:
            QMessageBox.warning(
                self,
                "Path Not Configured",
                f"The {meta['label']} path is not configured in Settings.",
            )
            return

        # Check conflicts first
        conflicts = self.manager.detect_conflicts(self.mod_type)
        if conflicts and self.config.show_conflict_warnings:
            reply = QMessageBox.warning(
                self,
                "Conflicts Detected",
                f"{len(conflicts)} conflict(s) found.\n"
                "Deploy anyway with potential unexpected effects?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        count, warnings = self.manager.deploy(self.mod_type, target_path)
        msg = f"Deployed {count} {meta['label']} to:\n{target_path}"
        if warnings:
            msg += "\n\nWarnings:\n" + "\n".join(warnings)
            QMessageBox.warning(self, "Deploy Complete with Warnings", msg)
        else:
            QMessageBox.information(self, "Deploy Complete", msg)

        self.emit_status(f"Deployed {count} {meta['label']}")
