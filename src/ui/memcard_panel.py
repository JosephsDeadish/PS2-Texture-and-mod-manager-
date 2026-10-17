"""Memory Card / Save File manager panel."""

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
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

logger = logging.getLogger(__name__)

_SAVE_SORTS = ("Card order", "Name (A–Z)", "Largest first")


def _filter_saves(saves, query, sort):
    terms = query.casefold().split()
    matches = [
        save for save in saves
        if all(term in f"{save.name} {save.dir_name}".casefold() for term in terms)
    ]
    if sort == "Name (A–Z)":
        matches.sort(key=lambda save: save.name.casefold())
    elif sort == "Largest first":
        matches.sort(key=lambda save: save.size_bytes, reverse=True)
    return matches


class MemoryCardPanel(BasePanel):
    """Panel for browsing and managing PS2 memory cards and saves."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("💾  Memory Cards", "Manage PS2 save files and memory cards", parent=parent)
        self.config = config
        self._current_card: str = ""
        self._all_saves = []
        self._card_exists = False
        self._card_valid = False
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._on_save_filter_changed)
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

    def _set_saves_placeholder_visible(self, visible: bool) -> None:
        placeholder = getattr(self, "_saves_empty_state", None)
        setter = getattr(placeholder, "setVisible", None)
        if callable(setter):
            setter(visible)
        elif placeholder is not None:
            toggler = getattr(placeholder, "show" if visible else "hide", None)
            if callable(toggler):
                toggler()

        saves_list = getattr(self, "_saves_list", None)
        setter = getattr(saves_list, "setVisible", None)
        if callable(setter):
            setter(not visible)
        elif saves_list is not None:
            toggler = getattr(saves_list, "hide" if visible else "show", None)
            if callable(toggler):
                toggler()

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
        if idx < 0 and isinstance(selected, str):
            try:
                if Path(selected).is_file():
                    self._card_combo.addItem(Path(selected).name, selected)
                    idx = self._card_combo.findData(selected)
            except OSError as exc:
                logger.warning("Could not inspect saved memory card %s: %s", selected, exc)
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

        if any(save.dir_name == save_name for save in self._all_saves):
            return  # Filtering temporarily hides the selected save.
        logger.warning(
            "Saved memory card save %r for %r is no longer available; clearing selection",
            save_name,
            self._current_card,
        )
        self._clear_selected_save_state("clearing missing memory card save selection")

    def _update_save_actions(self):
        item = self._saves_list.currentItem()
        selected = bool(item and item.data(Qt.ItemDataRole.UserRole))
        self._export_btn.setEnabled(self._card_valid and selected)
        self._copy_btn.setEnabled(self._card_valid and selected)
        self._import_btn.setEnabled(self._card_valid)
        self._export_all_btn.setEnabled(self._card_valid and bool(self._all_saves))
        self._backup_btn.setEnabled(self._card_exists)

    def _show_saves_empty(self, message, action, label):
        self._saves_empty_message.setText(message)
        self._empty_action = action
        self._saves_empty_action.setText(label)
        self._set_saves_placeholder_visible(True)

    def _on_empty_action(self):
        {
            "browse": self._browse_card,
            "import": self._import_save,
            "refresh": self._load_saves,
            "clear": self._clear_save_search,
        }[self._empty_action]()

    def _clear_save_search(self):
        self._search_edit.blockSignals(True)
        self._search_edit.clear()
        self._search_edit.blockSignals(False)
        self._on_save_filter_changed()

    def _restore_save_filters(self):
        bucket = self._panel_state_bucket()
        query = bucket.get("query", "")
        sort = bucket.get("sort", _SAVE_SORTS[0])
        self._search_edit.setText(query if isinstance(query, str) else "")
        self._sort_combo.setCurrentIndex(_SAVE_SORTS.index(sort) if sort in _SAVE_SORTS else 0)

    def _on_save_filter_changed(self, *_args):
        self._filter_timer.stop()
        self._panel_state_bucket().update({
            "query": self._search_edit.text().strip(),
            "sort": self._sort_combo.currentText(),
        })
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save memory card search settings: %s", exc)
        if self._card_valid:
            self._apply_save_filters()

    def hideEvent(self, event):
        if self._filter_timer.isActive():
            self._on_save_filter_changed()
        super().hideEvent(event)

    def _apply_save_filters(self):
        self._saves_loading = True
        try:
            self._saves_list.clear()
            saves = _filter_saves(
                self._all_saves, self._search_edit.text(), self._sort_combo.currentText(),
            )
            total = len(self._all_saves)
            self._saves_summary.setText(
                f"Showing {len(saves)} of {total} saves · "
                f"{sum(save.size_bytes for save in self._all_saves):,} bytes listed"
            )
            if not self._all_saves:
                self._show_saves_empty("No saves found on this card.", "import", "Import Save")
            elif not saves:
                self._show_saves_empty("No saves match your search.", "clear", "Clear Search")
            else:
                self._set_saves_placeholder_visible(False)
                for save in saves:
                    item = QListWidgetItem(
                        f"💾  {save.name}\n{save.dir_name} · {save.size_bytes:,} bytes"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, save.dir_name)
                    item.setToolTip(f"{save.dir_name}\nSize: {save.size_bytes:,} bytes")
                    self._saves_list.addItem(item)
            self._restore_selected_save()
        finally:
            self._saves_loading = False
            self._update_save_actions()

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
        self._card_combo.setMinimumWidth(180)
        self._card_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._card_combo.setMinimumContentsLength(16)
        self._card_combo.currentIndexChanged.connect(self._on_card_selected)
        card_row.addWidget(self._card_combo, 1)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        card_row.addWidget(refresh_btn)

        browse_btn = QPushButton("📁 Browse")
        browse_btn.clicked.connect(self._browse_card)
        card_row.addWidget(browse_btn)

        content.addLayout(card_row)
        card_actions = QHBoxLayout()
        new_btn = QPushButton("➕ New Card")
        new_btn.setToolTip("Create a new blank PS2 memory card")
        new_btn.setObjectName("primary_btn")
        new_btn.clicked.connect(self._create_card)
        card_actions.addWidget(new_btn)
        safety_hint = QLabel("Close PCSX2 before changing saves. Back up your card first.")
        safety_hint.setWordWrap(True)
        card_actions.addWidget(safety_hint, 1)

        content.addLayout(card_actions)

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
        self._info_lbl.setTextFormat(Qt.TextFormat.PlainText)
        info_layout.addWidget(self._info_lbl)
        info_layout.addStretch()

        export_all_btn = QPushButton("📤 Export All Saves")
        self._export_all_btn = export_all_btn
        export_all_btn.setToolTip("Export every save on the card, including saves hidden by search")
        export_all_btn.clicked.connect(self._export_all)
        info_layout.addWidget(export_all_btn)

        backup_btn = QPushButton("🗄 Backup Card")
        self._backup_btn = backup_btn
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

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search save names or directory IDs…")
        self._search_edit.setAccessibleName("Search memory card saves")
        self._search_edit.setClearButtonEnabled(True)
        right_layout.addWidget(self._search_edit)
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(_SAVE_SORTS)
        sort_row.addWidget(self._sort_combo)
        sort_row.addStretch()
        right_layout.addLayout(sort_row)
        self._saves_summary = QLabel()
        self._saves_summary.setWordWrap(True)
        right_layout.addWidget(self._saves_summary)

        self._saves_empty_state = QWidget()
        empty_layout = QVBoxLayout(self._saves_empty_state)
        empty_layout.addStretch()
        self._saves_empty_message = QLabel()
        self._saves_empty_message.setWordWrap(True)
        self._saves_empty_message.setTextFormat(Qt.TextFormat.PlainText)
        empty_layout.addWidget(self._saves_empty_message)
        self._saves_empty_action = QPushButton()
        self._saves_empty_action.clicked.connect(self._on_empty_action)
        empty_layout.addWidget(self._saves_empty_action)
        empty_layout.addStretch()
        right_layout.addWidget(self._saves_empty_state, 1)

        self._saves_list = QListWidget()
        self._saves_list.setWordWrap(True)
        self._saves_list.setStyleSheet(
            "QListWidget { background: #0f1830; border-radius: 6px; }"
            "QListWidget::item { padding: 8px; color: #e0e0e0; }"
            "QListWidget::item:selected { background: #e94560; }"
        )
        save_selection_changed = getattr(self._saves_list, "currentRowChanged", None)
        if callable(getattr(save_selection_changed, "connect", None)):
            save_selection_changed.connect(self._on_save_selected)
        right_layout.addWidget(self._saves_list, 1)
        self._set_saves_placeholder_visible(True)

        save_actions = QHBoxLayout()
        export_btn = QPushButton("📤 Export Selected")
        self._export_btn = export_btn
        export_btn.clicked.connect(self._export_selected)
        save_actions.addWidget(export_btn)

        copy_btn = QPushButton("📋 Copy to Other Card")
        self._copy_btn = copy_btn
        copy_btn.setToolTip("Copy selected save to another memory card")
        copy_btn.clicked.connect(self._copy_save_to_other_card)
        save_actions.addWidget(copy_btn)

        save_actions.addStretch()
        right_layout.addLayout(save_actions)

        import_btn = QPushButton("📥 Import Save")
        self._import_btn = import_btn
        import_btn.setToolTip("Import a .bin save dump into this memory card")
        import_btn.setObjectName("primary_btn")
        import_btn.clicked.connect(self._import_save)
        right_layout.addWidget(import_btn)

        splitter.addWidget(right_widget)
        splitter.setSizes([240, 460])
        self._splitter = splitter
        splitter_moved = getattr(splitter, "splitterMoved", None)
        if callable(getattr(splitter_moved, "connect", None)):
            splitter_moved.connect(self._save_splitter_sizes)
        self._restore_splitter_sizes()

        content.addWidget(splitter, 1)

        self._restore_save_filters()
        self._search_edit.textChanged.connect(lambda *_: self._filter_timer.start())
        self._sort_combo.currentIndexChanged.connect(self._on_save_filter_changed)
        self.refresh()

    def _on_save_selected(self, idx: int) -> None:
        self._update_save_actions()
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
            self._select_card_path(path)

    def _select_card_path(self, path):
        idx = self._card_combo.findData(path)
        if idx < 0:
            self._card_combo.addItem(Path(path).name, path)
            idx = self._card_combo.count() - 1
        self._card_combo.setCurrentIndex(idx)

    def _load_saves(self):
        self._saves_loading = True
        self._all_saves = []
        self._card_exists = False
        self._card_valid = False
        self._saves_summary.setText("")
        try:
            self._saves_list.clear()

            if not self._current_card:
                self._info_lbl.setText(
                    "No memory card selected\n"
                    "Choose a card above or browse for a card image."
                )
                self._show_saves_empty("Choose a memory card to browse its saves.", "browse", "Browse Cards")
                return

            card_path = Path(self._current_card)
            if not card_path.is_file():
                self._info_lbl.setText(
                    "File not found\n"
                    f"The selected memory card no longer exists:\n{card_path}"
                )
                self._show_saves_empty("The selected card no longer exists.", "browse", "Browse Cards")
                return

            self._card_exists = True
            size_mb = card_path.stat().st_size / (1024 * 1024)
            valid = is_valid_memcard(self._current_card)
            self._set_saves_placeholder_visible(False)

            self._info_lbl.setText(
                f"File: {card_path.name}\n"
                f"Size: {size_mb:.2f} MB\n"
                f"Valid PS2 card: {'Yes ✅' if valid else 'Unknown ⚠'}"
            )

            if not valid:
                self._info_lbl.setText(
                    f"File: {card_path.name}\n"
                    f"Size: {size_mb:.2f} MB\n"
                    "This file doesn't look like a valid PS2 memory card image."
                )
                self._show_saves_empty("This file is not a valid PS2 memory card.", "browse", "Choose Another Card")
                return

            try:
                self._all_saves = list_saves(self._current_card)
                self._card_valid = True
            except MemoryCardError as exc:
                logger.warning("Failed to load memory card saves for %s: %s", self._current_card, exc)
                self._show_saves_empty(f"Error reading card: {exc}", "refresh", "Retry")
                return
            self._apply_save_filters()
        except OSError as exc:
            logger.warning("Could not inspect memory card %s: %s", self._current_card, exc)
            self._info_lbl.setText(f"Could not read card: {exc}")
            self._show_saves_empty(f"Could not read card: {exc}", "refresh", "Retry")
        finally:
            self._saves_loading = False
            self._update_save_actions()

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
            self._select_card_path(path)
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
