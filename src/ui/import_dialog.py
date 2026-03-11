"""Import and Edit Mod Metadata dialogs for PS2 Mod Manager."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.mod import ModInfo, ModType


# ---------------------------------------------------------------------------
# Import Mod Dialog
# ---------------------------------------------------------------------------

class ImportModDialog(QDialog):
    """
    Shown before importing a mod.  Lets the user choose a source
    (folder or archive file) and optionally fill in metadata.
    """

    def __init__(self, mod_type: ModType, parent=None):
        super().__init__(parent)
        self.mod_type = mod_type
        self.setWindowTitle(f"Import {_type_label(mod_type)}")
        self.setMinimumSize(560, 480)

        # Results filled on accept
        self.source_path: str = ""
        self.meta: dict = {}

        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- Header ----
        header = QLabel(f"{_type_icon(self.mod_type)}  Import {_type_label(self.mod_type)}")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ---- Source ----
        src_group_lbl = QLabel("Source")
        src_group_lbl.setStyleSheet("font-weight: bold; color: #b0b0d0;")
        layout.addWidget(src_group_lbl)

        src_row = QHBoxLayout()
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("No source selected")
        self._src_edit.setReadOnly(True)
        src_row.addWidget(self._src_edit, 1)

        if _supports_folder(self.mod_type):
            folder_btn = QPushButton("📁 Folder")
            folder_btn.clicked.connect(self._choose_folder)
            src_row.addWidget(folder_btn)

        archive_btn = QPushButton("📦 Archive (.zip/.7z)")
        archive_btn.clicked.connect(self._choose_archive)
        src_row.addWidget(archive_btn)

        if not _supports_folder(self.mod_type):
            file_btn = QPushButton("📄 File")
            file_btn.clicked.connect(self._choose_file)
            src_row.addWidget(file_btn)

        layout.addLayout(src_row)

        # ---- Metadata ----
        meta_lbl = QLabel("Metadata  (optional)")
        meta_lbl.setStyleSheet("font-weight: bold; color: #b0b0d0; margin-top: 8px;")
        layout.addWidget(meta_lbl)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Inferred from folder/file name if blank")
        form.addRow("Name:", self._name_edit)

        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("Creator / uploader name")
        form.addRow("Author:", self._author_edit)

        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("e.g. 1.0.0")
        form.addRow("Version:", self._version_edit)

        self._gameid_edit = QLineEdit()
        self._gameid_edit.setPlaceholderText("e.g. SLUS-20062  (fetches cover art)")
        form.addRow("Game ID:", self._gameid_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("Short description…")
        self._desc_edit.setMaximumHeight(80)
        form.addRow("Description:", self._desc_edit)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://…")
        form.addRow("Source URL:", self._url_edit)

        layout.addLayout(form)

        # ---- Thumbnail note ----
        if self.mod_type in (ModType.TEXTURE_PACK, ModType.COVER_ART, ModType.PNACH, ModType.CHEAT):
            note = QLabel(
                "ℹ  If you enter a Game ID, PS2 Mod Manager will automatically\n"
                "download the cover art from GameTDB as the thumbnail."
            )
            note.setStyleSheet("color: #6070a0; font-size: 11px;")
            layout.addWidget(note)

        layout.addStretch()

        # ---- Buttons ----
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Import →")
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary_btn")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # Source pickers
    # ------------------------------------------------------------------

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, f"Select {_type_label(self.mod_type)} Folder"
        )
        if d:
            self._src_edit.setText(d)
            # Auto-fill name from folder
            if not self._name_edit.text():
                self._name_edit.setText(Path(d).name)
            # Auto-detect game serial
            self._auto_detect_game_id(d)

    def _choose_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {_type_label(self.mod_type)} Archive",
            "",
            "Archives (*.zip *.7z);;ZIP Files (*.zip);;7z Files (*.7z);;All Files (*)",
        )
        if path:
            self._src_edit.setText(path)
            if not self._name_edit.text():
                # Strip extension for default name
                stem = Path(path).stem
                self._name_edit.setText(stem)
            # Auto-detect game serial
            self._auto_detect_game_id(path)

    def _choose_file(self):
        from src.ui.mod_panel import _TYPE_META
        ext_filter = _TYPE_META.get(self.mod_type, {}).get(
            "ext_filter", "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {_type_label(self.mod_type)}", "", ext_filter
        )
        if path:
            self._src_edit.setText(path)
            if not self._name_edit.text():
                self._name_edit.setText(Path(path).stem)
            # Auto-detect game serial
            self._auto_detect_game_id(path)

    def _auto_detect_game_id(self, path: str):
        """Auto-fill Game ID and Name if a PS2 serial is detected in the filename."""
        if self._gameid_edit.text():
            return  # don't overwrite user-entered value
        try:
            from src.core.game_registry import detect_game_serial_from_file, serial_to_display
            serial = detect_game_serial_from_file(path)
            if serial:
                self._gameid_edit.setText(serial)
                # Show a helpful tooltip with the known game title
                title = serial_to_display(serial)
                self._gameid_edit.setToolTip(title)
                self._gameid_edit.setPlaceholderText(title)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def _accept(self):
        if not self._src_edit.text():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Source", "Please select a source folder or file.")
            return
        self.source_path = self._src_edit.text()
        self.meta = {
            "name": self._name_edit.text().strip(),
            "author": self._author_edit.text().strip(),
            "version": self._version_edit.text().strip(),
            "game_id": self._gameid_edit.text().strip(),
            "description": self._desc_edit.toPlainText().strip(),
            "source_url": self._url_edit.text().strip(),
        }
        self.accept()


# ---------------------------------------------------------------------------
# Edit Mod Metadata Dialog
# ---------------------------------------------------------------------------

class EditModDialog(QDialog):
    """Dialog for editing an existing mod's metadata fields."""

    def __init__(self, mod: ModInfo, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(f"Edit — {mod.name}")
        self.setMinimumSize(520, 420)
        self.updated_meta: dict = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel(f"✏️  Edit Mod Metadata")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit(self.mod.name)
        form.addRow("Name:", self._name_edit)

        self._author_edit = QLineEdit(self.mod.author)
        form.addRow("Author:", self._author_edit)

        self._version_edit = QLineEdit(self.mod.version)
        form.addRow("Version:", self._version_edit)

        self._gameid_edit = QLineEdit(self.mod.game_id)
        self._gameid_edit.setPlaceholderText("e.g. SLUS-20062")
        # Show known game title as tooltip if available
        try:
            from src.core.game_registry import serial_to_display
            if self.mod.game_id:
                self._gameid_edit.setToolTip(serial_to_display(self.mod.game_id))
        except ImportError:
            pass
        form.addRow("Game ID:", self._gameid_edit)

        self._tags_edit = QLineEdit(", ".join(self.mod.tags))
        self._tags_edit.setPlaceholderText("comma-separated tags")
        form.addRow("Tags:", self._tags_edit)

        self._desc_edit = QTextEdit(self.mod.description)
        self._desc_edit.setMaximumHeight(90)
        form.addRow("Description:", self._desc_edit)

        self._url_edit = QLineEdit(self.mod.source_url)
        self._url_edit.setPlaceholderText("https://…")
        form.addRow("Source URL:", self._url_edit)

        layout.addLayout(form)

        # Thumbnail refresh
        thumb_row = QHBoxLayout()
        thumb_row.addWidget(QLabel("Thumbnail:"))
        if self.mod.thumbnail_path and Path(self.mod.thumbnail_path).exists():
            thumb_status = QLabel("✅ Image present")
            thumb_status.setStyleSheet("color: #22c870;")
        else:
            thumb_status = QLabel("❌ No image")
            thumb_status.setStyleSheet("color: #e94560;")
        thumb_row.addWidget(thumb_status)
        thumb_row.addStretch()

        self._fetch_thumb_btn = QPushButton("🖼 Fetch from GameTDB")
        self._fetch_thumb_btn.setEnabled(bool(self._gameid_edit.text()))
        self._gameid_edit.textChanged.connect(
            lambda t: self._fetch_thumb_btn.setEnabled(bool(t))
        )
        self._fetch_thumb_btn.clicked.connect(self._fetch_thumbnail)
        thumb_row.addWidget(self._fetch_thumb_btn)

        layout.addLayout(thumb_row)

        self._thumb_status_lbl = QLabel("")
        self._thumb_status_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
        layout.addWidget(self._thumb_status_lbl)

        layout.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary_btn")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _fetch_thumbnail(self):
        game_id = self._gameid_edit.text().strip()
        if not game_id:
            return
        self._fetch_thumb_btn.setEnabled(False)
        self._thumb_status_lbl.setText("Fetching…")
        self._dialog_closed = False

        import threading
        from src.core.downloader import fetch_gametdb_art
        import src.core.config_manager as _cfg

        def _run():
            path = fetch_gametdb_art(game_id, str(_cfg.THUMBNAILS_DIR))
            # Only update UI if the dialog is still open
            if not getattr(self, "_dialog_closed", True):
                if path:
                    self._thumb_status_lbl.setText(f"✅ Saved: {path}")
                    # Store for later use
                    self._fetched_thumbnail = path
                else:
                    self._thumb_status_lbl.setText("❌ Not found on GameTDB")
                self._fetch_thumb_btn.setEnabled(True)

        self._fetched_thumbnail = ""
        threading.Thread(target=_run, daemon=True).start()

    def closeEvent(self, event):
        """Mark dialog as closed so background thumbnail fetch won't touch widgets."""
        self._dialog_closed = True
        super().closeEvent(event)

    def reject(self):
        self._dialog_closed = True
        super().reject()

    def accept(self):
        self._dialog_closed = True
        super().accept()

    def _save(self):
        tags_raw = self._tags_edit.text().strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        self.updated_meta = {
            "name": self._name_edit.text().strip() or self.mod.name,
            "author": self._author_edit.text().strip(),
            "version": self._version_edit.text().strip(),
            "game_id": self._gameid_edit.text().strip(),
            "description": self._desc_edit.toPlainText().strip(),
            "source_url": self._url_edit.text().strip(),
            "tags": tags,
        }
        # Attach thumbnail path if we just fetched one
        thumb = getattr(self, "_fetched_thumbnail", "")
        if thumb:
            self.updated_meta["thumbnail_path"] = thumb
        self.accept()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_label(mod_type: ModType) -> str:
    return {
        ModType.TEXTURE_PACK: "Texture Pack",
        ModType.PNACH: "PNACH Patch",
        ModType.COVER_ART: "Cover Art",
        ModType.SAVE_FILE: "Save File",
        ModType.CHEAT: "Cheat File",
    }.get(mod_type, "Mod")


def _type_icon(mod_type: ModType) -> str:
    return {
        ModType.TEXTURE_PACK: "🎨",
        ModType.PNACH: "🔧",
        ModType.COVER_ART: "🖼️",
        ModType.SAVE_FILE: "💾",
        ModType.CHEAT: "⚡",
    }.get(mod_type, "📦")


def _supports_folder(mod_type: ModType) -> bool:
    """Return True for mod types that are typically delivered as folders."""
    return mod_type == ModType.TEXTURE_PACK
