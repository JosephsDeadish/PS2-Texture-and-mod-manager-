"""Memory Card / Save File manager panel."""

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
    create_memcard,
    export_save,
    is_valid_memcard,
    list_memcard_files,
    list_saves,
)
from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel
from src.ui.widgets import EmptyStateWidget


class MemoryCardPanel(BasePanel):
    """Panel for browsing and managing PS2 memory cards and saves."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("💾  Memory Cards", "Manage PS2 save files and memory cards", parent=parent)
        self.config = config
        self._current_card: str = ""
        self._build()

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
        right_layout.addWidget(self._saves_list, 1)

        save_actions = QHBoxLayout()
        export_btn = QPushButton("📤 Export Selected")
        export_btn.clicked.connect(self._export_selected)
        save_actions.addWidget(export_btn)
        save_actions.addStretch()
        right_layout.addLayout(save_actions)

        splitter.addWidget(right_widget)
        splitter.setSizes([240, 460])

        content.addWidget(splitter, 1)

        self.refresh()

    def refresh(self):
        """Reload the list of memory card files."""
        self._card_combo.blockSignals(True)
        self._card_combo.clear()
        self._card_combo.addItem("— Select a memory card —", "")

        cards_dir = self.config.memcards_path
        if cards_dir:
            for path in list_memcard_files(cards_dir):
                self._card_combo.addItem(Path(path).name, path)

        self._card_combo.blockSignals(False)
        self._load_saves()

    def _on_card_selected(self, idx: int):
        path = self._card_combo.itemData(idx)
        self._current_card = path or ""
        self._load_saves()

    def _browse_card(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Memory Card",
            self.config.memcards_path or "",
            "Memory Cards (*.ps2 *.mcd *.mc2);;All Files (*)",
        )
        if path:
            # Add to combo if not already there
            for i in range(self._card_combo.count()):
                if self._card_combo.itemData(i) == path:
                    self._card_combo.setCurrentIndex(i)
                    return
            self._card_combo.addItem(Path(path).name, path)
            self._card_combo.setCurrentIndex(self._card_combo.count() - 1)

    def _load_saves(self):
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
        except MemoryCardError as exc:
            self._saves_list.addItem(f"Error reading card: {exc}")

    def _create_card(self):
        """Create a new blank PCSX2-format memory card image."""
        # Get destination folder — prefer configured memcards dir
        cards_dir = self.config.memcards_path
        if not cards_dir:
            cards_dir = QFileDialog.getExistingDirectory(
                self, "Choose folder for new memory card"
            )
            if not cards_dir:
                return

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

        dest = QFileDialog.getExistingDirectory(self, "Export Save To…")
        if not dest:
            return

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

        dest = QFileDialog.getExistingDirectory(self, "Export All Saves To…")
        if not dest:
            return

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
