"""Memory Card / Save File manager panel."""

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.core.memory_card import (
    MemoryCardError,
    backup_memcard,
    copy_save_between_cards,
    create_memcard,
    export_save,
    import_raw_save,
    is_valid_memcard,
    list_memcard_files,
    list_saves,
)
from src.core.config_manager import save_config, ui_state_bucket
from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel
from src.ui.widgets import EmptyStateWidget

logger = logging.getLogger(__name__)


class MemoryCardPanel(BasePanel):
    """Panel for browsing and managing PS2 memory cards and saves."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("💾  Memory Cards", "Manage PS2 save files and memory cards", parent=parent)
        self.config = config
        self._current_card: str = ""
        self._build()

    def _last_paths_bucket(self) -> dict:
        return ui_state_bucket(self.config, "last_paths")

    def _panel_state_bucket(self) -> dict:
        return ui_state_bucket(self.config, "memcard_panel")

    def _selected_save_bucket(self) -> dict:
        bucket = self._panel_state_bucket().setdefault("selected_save_dir_by_card", {})
        if not isinstance(bucket, dict):
            bucket = {}
            self._panel_state_bucket()["selected_save_dir_by_card"] = bucket
        return bucket

    def _remember_last_path(self, key: str, path: str) -> None:
        self._last_paths_bucket()[key] = path
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card panel state after %s: %s", key, exc)

    def _remember_selected_card(self, path: str) -> None:
        self._panel_state_bucket()["selected_card"] = path
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card selection: %s", exc)

    def _remember_selected_save(self, save_name: str) -> None:
        if not self._current_card or not save_name:
            return
        bucket = self._selected_save_bucket()
        if bucket.get(self._current_card) == save_name:
            return
        bucket[self._current_card] = save_name
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card save selection: %s", exc)

    def _clear_selected_save_state(self, context: str) -> None:
        if not self._current_card:
            return
        bucket = self._panel_state_bucket().get("selected_save_dir_by_card", {})
        if not isinstance(bucket, dict) or self._current_card not in bucket:
            return
        bucket.pop(self._current_card, None)
        if not bucket:
            self._panel_state_bucket().pop("selected_save_dir_by_card", None)
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card save selection after %s: %s", context, exc)

    def _validated_splitter_sizes(self, sizes, *, action: str):
        if not isinstance(sizes, (list, tuple)):
            logger.warning(
                "Ignoring invalid memory card splitter state while %s: expected a list, got %r",
                action,
                sizes,
            )
            return None
        try:
            cleaned = [int(size) for size in sizes]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Ignoring invalid memory card splitter state while %s: %s",
                action,
                exc,
            )
            return None
        if len(cleaned) < 2:
            logger.warning(
                "Ignoring invalid memory card splitter state while %s: expected at least 2 sizes, got %r",
                action,
                cleaned,
            )
            return None
        return cleaned

    def _save_splitter_sizes(self, *_args) -> None:
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        cleaned = self._validated_splitter_sizes(
            getattr(splitter, "sizes", lambda: [])(),
            action="saving",
        )
        if cleaned is None:
            return
        self._panel_state_bucket()["splitter_sizes"] = cleaned
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card splitter sizes: %s", exc)

    def _restore_splitter_sizes(self) -> None:
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        cleaned = self._validated_splitter_sizes(
            self._panel_state_bucket().get("splitter_sizes", []),
            action="restoring",
        )
        if cleaned is None:
            return
        if hasattr(splitter, "setSizes"):
            splitter.setSizes(cleaned)

    def _restore_selected_card(self) -> None:
        selected = self._current_card or self._panel_state_bucket().get("selected_card", "") or ""
        if not selected:
            self._current_card = ""
            return

        idx = self._card_combo.findData(selected)
        if idx >= 0:
            self._card_combo.setCurrentIndex(idx)
            self._current_card = selected
            return

        logger.warning(
            "Saved memory card selection %r is no longer available; using the default entry",
            selected,
        )
        self._current_card = ""
        self._card_combo.setCurrentIndex(0)

    def _restore_selected_save(self) -> None:
        if not self._current_card:
            return
        bucket = self._panel_state_bucket().get("selected_save_dir_by_card", {})
        if not isinstance(bucket, dict):
            logger.warning(
                "Saved memory card save selection state is invalid; clearing selection"
            )
            self._panel_state_bucket().pop("selected_save_dir_by_card", None)
            try:
                save_config(self.config)
            except Exception as exc:
                logger.warning("Could not save memory card save selection reset: %s", exc)
            return
        save_name = bucket.get(self._current_card, "")
        if not isinstance(save_name, str) or not save_name:
            return

        for idx in range(self._saves_list.count()):
            item = self._saves_list.item(idx)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) != save_name:
                continue
            self._save_selection_syncing = True
            try:
                self._saves_list.setCurrentRow(idx)
            finally:
                self._save_selection_syncing = False
            return

        logger.warning(
            "Saved memory card save %r for %r is no longer available; clearing selection",
            save_name,
            self._current_card,
        )
        self._clear_selected_save_state("clearing missing memory card save selection")

    def _build(self):
        content = self._content_layout

        # ---- Card selection row ----
        card_row = QHBoxLayout()
        card_row.setSpacing(8)

        card_row.addWidget(QLabel("Memory Card:"))
        self._card_combo = QComboBox()
        self._card_combo.setSizePolicy(
            self._card_combo.sizePolicy().horizontalPolicy(),
            self._card_combo.sizePolicy().verticalPolicy()
        )
        self._card_combo.setMinimumWidth(300)
        self._card_combo.currentIndexChanged.connect(self._on_card_selected)
        card_row.addWidget(self._card_combo, 1)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        card_row.addWidget(refresh_btn)

        browse_btn = QPushButton("📁 Browse")
        browse_btn.clicked.connect(self._browse_card)
        card_row.addWidget(browse_btn)

        new_btn = QPushButton("➕ New Card")
        new_btn.setToolTip("Create a new blank PS2 memory card")
        new_btn.setObjectName("primary_btn")
        new_btn.clicked.connect(self._create_card)
        card_row.addWidget(new_btn)

        content.addLayout(card_row)

        # ---- Splitter: card info + saves list ----
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: card info
        info_frame = QFrame()
        info_frame.setObjectName("card")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(8)

        info_title = QLabel("Card Info")
        info_title.setStyleSheet("font-weight: bold; color: #b0b0d0;")
        info_layout.addWidget(info_title)

        self._info_lbl = QLabel("No card selected")
        self._info_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        self._info_lbl.setWordWrap(True)
        info_layout.addWidget(self._info_lbl)
        info_layout.addStretch()

        export_all_btn = QPushButton("📤 Export All Saves")
        export_all_btn.clicked.connect(self._export_all)
        info_layout.addWidget(export_all_btn)

        backup_btn = QPushButton("🗄 Backup Card")
        backup_btn.setToolTip("Create a timestamped backup copy of this memory card")
        backup_btn.clicked.connect(self._backup_card)
        info_layout.addWidget(backup_btn)

        splitter.addWidget(info_frame)

        # Right: saves list
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        saves_title = QLabel("Save Files")
        saves_title.setStyleSheet("font-weight: bold; color: #b0b0d0;")
        right_layout.addWidget(saves_title)

        self._saves_list = QListWidget()
        self._saves_list.setStyleSheet(
            "QListWidget { background: #0f1830; border-radius: 6px; }"
            "QListWidget::item { padding: 8px; color: #e0e0e0; }"
            "QListWidget::item:selected { background: #e94560; }"
        )
        save_selection_changed = getattr(self._saves_list, "currentRowChanged", None)
        if callable(getattr(save_selection_changed, "connect", None)):
            save_selection_changed.connect(self._on_save_selected)
        right_layout.addWidget(self._saves_list, 1)

        save_actions = QHBoxLayout()
        export_btn = QPushButton("📤 Export Selected")
        export_btn.clicked.connect(self._export_selected)
        save_actions.addWidget(export_btn)

        import_btn = QPushButton("📥 Import Save")
        import_btn.setToolTip("Import a .bin save dump into this memory card")
        import_btn.setObjectName("primary_btn")
        import_btn.clicked.connect(self._import_save)
        save_actions.addWidget(import_btn)

        copy_btn = QPushButton("📋 Copy to Other Card")
        copy_btn.setToolTip("Copy selected save to another memory card")
        copy_btn.clicked.connect(self._copy_save_to_other_card)
        save_actions.addWidget(copy_btn)

        save_actions.addStretch()
        right_layout.addLayout(save_actions)

        splitter.addWidget(right_widget)
        splitter.setSizes([240, 460])
        self._splitter = splitter
        splitter_moved = getattr(splitter, "splitterMoved", None)
        if callable(getattr(splitter_moved, "connect", None)):
            splitter_moved.connect(self._save_splitter_sizes)
        self._restore_splitter_sizes()

        content.addWidget(splitter, 1)

        self.refresh()

    def _on_save_selected(self, idx: int) -> None:
        if getattr(self, "_saves_loading", False) or getattr(self, "_save_selection_syncing", False):
            return
        item = self._saves_list.currentItem()
        if item is None:
            self._clear_selected_save_state("clearing memory card save selection")
            return
        save_name = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(save_name, str) or not save_name:
            self._clear_selected_save_state("clearing memory card save selection")
            return
        self._remember_selected_save(save_name)

    def refresh(self):
        """Reload the list of memory card files."""
        self._card_combo.blockSignals(True)
        self._card_combo.clear()
        self._card_combo.addItem("— Select a memory card —", "")

        cards_dir = self.config.memcards_path
        if cards_dir:
            for path in list_memcard_files(cards_dir):
                self._card_combo.addItem(Path(path).name, path)

        self._restore_selected_card()
        self._card_combo.blockSignals(False)
        self._load_saves()

    def _on_card_selected(self, idx: int):
        path = self._card_combo.itemData(idx)
        self._current_card = path or ""
        self._remember_selected_card(self._current_card)
        self._load_saves()

    def _browse_card(self):
        last_paths = self._last_paths_bucket()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Memory Card",
            last_paths.get("memcard_card_dir", self.config.memcards_path or ""),
            "Memory Cards (*.ps2 *.mcd *.mc2 *.bin);;All Files (*)",
        )
        if path:
            self._remember_last_path("memcard_card_dir", str(Path(path).parent))
            # Add to combo if not already there
            for i in range(self._card_combo.count()):
                if self._card_combo.itemData(i) == path:
                    self._card_combo.setCurrentIndex(i)
                    return
            self._card_combo.addItem(Path(path).name, path)
            self._card_combo.setCurrentIndex(self._card_combo.count() - 1)

    def _load_saves(self):
        self._saves_loading = True
        try:
            self._saves_list.clear()

            if not self._current_card:
                self._info_lbl.setText("No card selected")
                return

            card_path = Path(self._current_card)
            if not card_path.is_file():
                self._info_lbl.setText("File not found")
                return

            size_mb = card_path.stat().st_size / (1024 * 1024)
            valid = is_valid_memcard(self._current_card)

            self._info_lbl.setText(
                f"File: {card_path.name}\n"
                f"Size: {size_mb:.2f} MB\n"
                f"Valid PS2 card: {'Yes ✅' if valid else 'Unknown ⚠'}"
            )

            if not valid:
                self._saves_list.addItem("(Not a recognized PS2 memory card)")
                return

            try:
                saves = list_saves(self._current_card)
                if not saves:
                    item = QListWidgetItem("💾  (No saves found)")
                    item.setForeground(Qt.GlobalColor.gray)
                    self._saves_list.addItem(item)
                else:
                    for save in saves:
                        item = QListWidgetItem(f"💾  {save.name}")
                        item.setData(Qt.ItemDataRole.UserRole, save.dir_name)
                        item.setToolTip(f"Size: {save.size_bytes} bytes")
                        self._saves_list.addItem(item)
                    self._restore_selected_save()
            except MemoryCardError as exc:
                logger.warning("Failed to load memory card saves for %s: %s", self._current_card, exc)
                self._saves_list.addItem(f"Error reading card: {exc}")
        finally:
            self._saves_loading = False

    def _create_card(self):
        """Create a new blank PCSX2-format memory card image."""
        # Get destination folder — prefer configured memcards dir
        cards_dir = self.config.memcards_path
        if not cards_dir:
            last_paths = self._last_paths_bucket()
            cards_dir = QFileDialog.getExistingDirectory(
                self,
                "Choose folder for new memory card",
                last_paths.get("memcard_new_card_dir", ""),
            )
            if not cards_dir:
                return
            self._remember_last_path("memcard_new_card_dir", cards_dir)

        name, ok = QInputDialog.getText(
            self,
            "New Memory Card",
            "Card filename (without extension):",
            text="MemoryCard1",
        )
        if not ok or not name.strip():
            return

        filename = name.strip()
        if not filename.endswith(".ps2"):
            filename += ".ps2"

        dest_path = str(Path(cards_dir) / filename)

        try:
            path = create_memcard(dest_path)
            QMessageBox.information(
                self,
                "Memory Card Created",
                f"New memory card created at:\n{path}\n\n"
                "PCSX2 will initialise the card structure the first time it is used.",
            )
            self.emit_status(f"Created memory card: {filename}")
            self.refresh()
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _export_selected(self):
        item = self._saves_list.currentItem()
        if not item:
            QMessageBox.information(self, "No Selection", "Please select a save to export.")
            return

        save_name = item.data(Qt.ItemDataRole.UserRole)
        if not save_name:
            return

        last_paths = self._last_paths_bucket()
        dest = QFileDialog.getExistingDirectory(
            self,
            "Export Save To…",
            last_paths.get("memcard_export_dir", ""),
        )
        if not dest:
            return
        self._remember_last_path("memcard_export_dir", dest)

        try:
            path = export_save(self._current_card, save_name, dest)
            QMessageBox.information(
                self, "Export Complete", f"Save exported to:\n{path}"
            )
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_all(self):
        if not self._current_card:
            QMessageBox.information(self, "No Card", "Please select a memory card first.")
            return

        last_paths = self._last_paths_bucket()
        dest = QFileDialog.getExistingDirectory(
            self,
            "Export All Saves To…",
            last_paths.get("memcard_export_dir", ""),
        )
        if not dest:
            return
        self._remember_last_path("memcard_export_dir", dest)

        try:
            saves = list_saves(self._current_card)
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        errors = []
        for save in saves:
            try:
                export_save(self._current_card, save.dir_name, dest)
            except MemoryCardError as exc:
                errors.append(f"{save.name}: {exc}")

        msg = f"Exported {len(saves) - len(errors)} save(s) to {dest}"
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)
            QMessageBox.warning(self, "Export Complete with Errors", msg)
        else:
            QMessageBox.information(self, "Export Complete", msg)

    # ------------------------------------------------------------------
    # Backup card
    # ------------------------------------------------------------------

    def _backup_card(self):
        """Back up the current memory card to a timestamped file."""
        if not self._current_card:
            QMessageBox.information(self, "No Card", "Please select a memory card first.")
            return

        last_paths = self._last_paths_bucket()
        dest_dir = QFileDialog.getExistingDirectory(
            self, "Choose backup destination folder",
            last_paths.get("memcard_backup_dir", self.config.memcards_path or ""),
        )
        if not dest_dir:
            return
        self._remember_last_path("memcard_backup_dir", dest_dir)

        try:
            backup_path = backup_memcard(self._current_card, dest_dir)
            QMessageBox.information(
                self, "Backup Complete",
                f"Memory card backed up to:\n{backup_path}"
            )
            self.emit_status(f"Backup saved: {Path(backup_path).name}")
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Backup Error", str(exc))

    # ------------------------------------------------------------------
    # Import save into card
    # ------------------------------------------------------------------

    def _import_save(self):
        """Import a .bin save dump into the current memory card."""
        if not self._current_card:
            QMessageBox.information(self, "No Card", "Please select a memory card first.")
            return

        last_paths = self._last_paths_bucket()
        src_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Save File to Import",
            last_paths.get("memcard_import_file_dir", self.config.memcards_path or ""),
            "Save Dumps (*.bin);;All Files (*)",
        )
        if not src_path:
            return
        self._remember_last_path("memcard_import_file_dir", str(Path(src_path).parent))

        save_name, ok = QInputDialog.getText(
            self,
            "Save Name",
            "Enter the save directory name (e.g. BISLUS-12345):",
            text=Path(src_path).stem,
        )
        if not ok or not save_name.strip():
            return

        # Warn user before writing
        reply = QMessageBox.warning(
            self,
            "Write to Memory Card",
            "This will modify your memory card image.\n"
            "Make sure you have a backup before continuing.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            found = import_raw_save(src_path, self._current_card, save_name.strip())
            verb = "updated" if found else "appended"
            QMessageBox.information(
                self, "Import Complete",
                f"Save '{save_name.strip()}' has been {verb} in the memory card."
            )
            self.emit_status(f"Save imported: {save_name.strip()}")
            self._load_saves()
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Import Error", str(exc))

    # ------------------------------------------------------------------
    # Copy save to another card
    # ------------------------------------------------------------------

    def _copy_save_to_other_card(self):
        """Copy the selected save to a different memory card."""
        item = self._saves_list.currentItem()
        if not item:
            QMessageBox.information(self, "No Selection", "Please select a save to copy.")
            return

        save_name = item.data(Qt.ItemDataRole.UserRole)
        if not save_name:
            return

        last_paths = self._last_paths_bucket()
        dest_card, _ = QFileDialog.getOpenFileName(
            self,
            "Select Destination Memory Card",
            last_paths.get("memcard_copy_card_dir", self.config.memcards_path or ""),
            "Memory Cards (*.ps2 *.mcd *.mc2 *.bin);;All Files (*)",
        )
        if not dest_card:
            return
        self._remember_last_path("memcard_copy_card_dir", str(Path(dest_card).parent))

        if dest_card == self._current_card:
            QMessageBox.warning(self, "Same Card", "Source and destination are the same card.")
            return

        import tempfile
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = copy_save_between_cards(
                    self._current_card, save_name, dest_card, tmp
                )
            verb = "updated" if result else "added"
            QMessageBox.information(
                self, "Copy Complete",
                f"Save '{save_name}' has been {verb} in:\n{dest_card}"
            )
            self.emit_status(f"Copied '{save_name}' → {Path(dest_card).name}")
        except MemoryCardError as exc:
            QMessageBox.critical(self, "Copy Error", str(exc))
