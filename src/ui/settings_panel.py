"""Settings panel for PS2 Mod Manager."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import save_config
from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel
from src.ui.widgets import PathChooser


class SettingsPanel(BasePanel):
    """Settings/preferences panel."""

    settings_saved = pyqtSignal(AppConfig)
    rerun_wizard = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("⚙️  Settings", "Configure PS2 Mod Manager", parent=parent)
        self.config = config
        self._build()

    def _build(self):
        content = self._content_layout

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ---- PCSX2 Paths ----
        layout.addWidget(_section("PCSX2 Paths"))

        self._pcsx2_chooser = PathChooser("PCSX2 Config Dir:")
        self._pcsx2_chooser.set_path(self.config.pcsx2_path)
        layout.addWidget(self._pcsx2_chooser)

        auto_btn = QPushButton("🔍 Auto-detect from PCSX2 path")
        auto_btn.clicked.connect(self._auto_detect)
        layout.addWidget(auto_btn)

        self._tex_chooser = PathChooser("Textures Folder:")
        self._tex_chooser.set_path(self.config.textures_path)
        layout.addWidget(self._tex_chooser)

        self._pnach_chooser = PathChooser("PNACH/Patches Folder:")
        self._pnach_chooser.set_path(self.config.pnach_path)
        layout.addWidget(self._pnach_chooser)

        self._covers_chooser = PathChooser("Cover Art Folder:")
        self._covers_chooser.set_path(self.config.cover_art_path)
        layout.addWidget(self._covers_chooser)

        self._memcards_chooser = PathChooser("Memory Cards Folder:")
        self._memcards_chooser.set_path(self.config.memcards_path)
        layout.addWidget(self._memcards_chooser)

        self._cheats_chooser = PathChooser("Cheats (WS) Folder:")
        self._cheats_chooser.set_path(self.config.cheats_path)
        layout.addWidget(self._cheats_chooser)

        self._storage_chooser = PathChooser("Mod Storage Folder:")
        self._storage_chooser.set_path(self.config.mods_storage_path)
        layout.addWidget(self._storage_chooser)

        layout.addWidget(_sep())

        # ---- Behaviour ----
        layout.addWidget(_section("Behaviour"))

        self._conflicts_check = QCheckBox("Show conflict warnings before deploying")
        self._conflicts_check.setChecked(self.config.show_conflict_warnings)
        layout.addWidget(self._conflicts_check)

        self._updates_check = QCheckBox("Check for mod updates on startup")
        self._updates_check.setChecked(self.config.check_updates_on_start)
        layout.addWidget(self._updates_check)

        layout.addWidget(_sep())

        # ---- Wizard ----
        layout.addWidget(_section("Setup"))

        wizard_btn = QPushButton("🧙 Re-run Setup Wizard")
        wizard_btn.clicked.connect(self.rerun_wizard.emit)
        layout.addWidget(wizard_btn)

        layout.addStretch()
        scroll.setWidget(container)
        content.addWidget(scroll, 1)

        # ---- Save button ----
        save_btn = QPushButton("💾 Save Settings")
        save_btn.setObjectName("primary_btn")
        save_btn.clicked.connect(self._save)
        content.addWidget(save_btn)

    def _save(self):
        self.config.pcsx2_path = self._pcsx2_chooser.get_path()
        self.config.textures_path = self._tex_chooser.get_path()
        self.config.pnach_path = self._pnach_chooser.get_path()
        self.config.cover_art_path = self._covers_chooser.get_path()
        self.config.memcards_path = self._memcards_chooser.get_path()
        self.config.cheats_path = self._cheats_chooser.get_path()
        self.config.mods_storage_path = self._storage_chooser.get_path()
        self.config.show_conflict_warnings = self._conflicts_check.isChecked()
        self.config.check_updates_on_start = self._updates_check.isChecked()

        save_config(self.config)
        self.settings_saved.emit(self.config)
        self.emit_status("Settings saved ✅")
        QMessageBox.information(self, "Saved", "Settings have been saved.")

    def _auto_detect(self):
        from src.core.config_manager import detect_pcsx2_paths
        path = self._pcsx2_chooser.get_path()
        if not path:
            QMessageBox.warning(self, "No Path", "Please set the PCSX2 config directory first.")
            return
        paths = detect_pcsx2_paths(path)
        self._tex_chooser.set_path(paths.get("textures_path", ""))
        self._pnach_chooser.set_path(paths.get("pnach_path", ""))
        self._covers_chooser.set_path(paths.get("cover_art_path", ""))
        self._memcards_chooser.set_path(paths.get("memcards_path", ""))
        self._cheats_chooser.set_path(paths.get("cheats_path", ""))

    def reload_config(self, config: AppConfig):
        """Update displayed values when config changes."""
        self.config = config
        self._pcsx2_chooser.set_path(config.pcsx2_path)
        self._tex_chooser.set_path(config.textures_path)
        self._pnach_chooser.set_path(config.pnach_path)
        self._covers_chooser.set_path(config.cover_art_path)
        self._memcards_chooser.set_path(config.memcards_path)
        self._cheats_chooser.set_path(config.cheats_path)
        self._storage_chooser.set_path(config.mods_storage_path)
        self._conflicts_check.setChecked(config.show_conflict_warnings)
        self._updates_check.setChecked(config.check_updates_on_start)


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #b0b0d0;")
    return lbl


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    return f
