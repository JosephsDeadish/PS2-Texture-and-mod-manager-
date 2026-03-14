"""Generic mod management panel for texture packs, pnach, cover art, saves, cheats."""

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

    # Emitted when the user asks to view mods by an author in a *different* panel type.
    # Payload: (author: str, target_mod_type: ModType)
    navigate_to_author_type = pyqtSignal(str, object)

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
        self._library_filter_check.setToolTip(
            "Show only mods whose game serial matches a disc image\n"
            "in your Game Library folder (configure in Settings)."
        )
        self._library_filter_check.setStyleSheet("color: #80b0ff; font-size: 12px;")
        self._library_filter_check.stateChanged.connect(self._apply_filter)
        author_row.addWidget(self._library_filter_check)

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
        library_only = self._library_filter_check.isChecked()
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

        # Conflict info
        conflicts = self.manager.detect_conflicts(self.mod_type)
        conflicting_ids = set()
        for c in conflicts:
            conflicting_ids.add(c.mod_a_id)
            conflicting_ids.add(c.mod_b_id)

        # Shadowed mod detection (only for texture packs where file-level tracking matters)
        shadowed_ids: set = set()
        if self.mod_type == ModType.TEXTURE_PACK:
            shadowed_map = self.manager.detect_shadowed_mods(self.mod_type)
            shadowed_ids = set(shadowed_map.keys())

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
                widget = ModItemWidget(
                    mod,
                    has_conflict=(mod.id in conflicting_ids),
                    is_shadowed=(mod.id in shadowed_ids),
                )
                widget.toggled.connect(self._on_toggle)
                widget.remove_requested.connect(self._on_remove)
                widget.priority_up.connect(self._on_priority_up)
                widget.priority_down.connect(self._on_priority_down)
                widget.details_requested.connect(self._on_details)
                widget.edit_requested.connect(self._on_edit)
                widget.filter_by_author.connect(self._filter_by_author)
                self._list_layout.insertWidget(i, widget)

        enabled_count = sum(1 for m in self.db.by_type(self.mod_type) if m.enabled)
        total_count = len(self.db.by_type(self.mod_type))
        shadow_note = f"  •  {len(shadowed_ids)} shadowed" if shadowed_ids else ""
        self._count_lbl.setText(
            f"{enabled_count}/{total_count} enabled"
            + (f"  •  {len(conflicts)} conflict(s)" if conflicts else "")
            + shadow_note
        )

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
            dlg.see_more_by_author.connect(self._on_see_more_by_author)
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
            return frozenset()
        try:
            from src.core.game_library import get_library_serials
            return get_library_serials(path)
        except Exception:
            return frozenset()

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
        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")
        for mod in self.db.by_type(self.mod_type):
            if not mod.enabled:
                mod.enabled = True
                self.db.update(mod)
        # Single bulk deploy after all flags are set
        if target_path:
            count, _ = self.manager.deploy(self.mod_type, target_path)
            self.emit_status(f"All {meta['label'].lower()} enabled — deployed {count} to PCSX2")
        else:
            self.emit_status(f"All {meta['label'].lower()} enabled (configure path in Settings to deploy)")
        self._apply_filter()

    def _disable_all(self):
        meta = _TYPE_META[self.mod_type]
        target_path = getattr(self.config, meta["deploy_key"], "")
        for mod in self.db.by_type(self.mod_type):
            if mod.enabled:
                mod.enabled = False
                self.db.update(mod)
        # Re-deploy (nothing enabled → clears deployed files via empty deploy)
        if target_path:
            self.manager.deploy(self.mod_type, target_path)
        self.emit_status(f"All {meta['label'].lower()} disabled")
        self._apply_filter()

    def _show_conflicts(self):
        conflicts = self.manager.detect_conflicts(self.mod_type)
        pnach_conflicts = []
        if self.mod_type in (ModType.PNACH, ModType.CHEAT):
            try:
                pnach_conflicts = self.manager.detect_pnach_conflicts(self.mod_type)
            except Exception:
                pass

        if not conflicts and not pnach_conflicts:
            QMessageBox.information(
                self, "No Conflicts", "No conflicts detected between enabled mods! ✅"
            )
            return
        dlg = ConflictDialog(conflicts, self.db, self, pnach_conflicts=pnach_conflicts)
        dlg.exec()
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
        except Exception:
            pass

        # Try to pre-fill the game serial from the current library filter
        serial = ""
        try:
            if hasattr(self, '_library_filter_check') and self._library_filter_check.isChecked():
                # Get currently shown mods and infer serial from them
                mods = self.manager.list_mods(self.mod_type)
                enabled_serials = {m.game_id for m in mods if m.enabled and m.game_id}
                if len(enabled_serials) == 1:
                    serial = enabled_serials.pop()
        except Exception:
            pass

        dlg = PnachCodeBuilderDialog(
            game_serial=serial,
            cheats_dir=cheats_dir,
            config=self.config,
            parent=self,
        )
        dlg.exec()

    def _check_updates(self):
        """
        Run the update checker for all mods in this panel that have a source URL.
        Results are shown in a summary dialog; mods with available updates get an
        "↑ Update" badge and the list is refreshed.
        """
        from src.core.updater import UpdateChecker

        mods_with_source = [
            m for m in self.db.by_type(self.mod_type)
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
            self._apply_filter()
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
