"""Settings panel for PS2 Mod Manager."""

from PyQt6.QtCore import pyqtSignal, Qt
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
from src.ui.theme import THEME_KEYS, apply_theme

PATREON_URL = "https://www.patreon.com/c/DeadOnTheInside"
APP_VERSION = "1.0.0"


class SettingsPanel(BasePanel):
    """Settings/preferences panel."""

    settings_saved = pyqtSignal(AppConfig)
    rerun_wizard = pyqtSignal()
    theme_changed = pyqtSignal(str)  # emits the new theme key when changed

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

        self._partial_tex_chooser = PathChooser("Partial Textures Folder:")
        self._partial_tex_chooser.set_path(self.config.partial_textures_path)
        layout.addWidget(self._partial_tex_chooser)

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

        deploy_note = QLabel(
            "ℹ  Mods are deployed to PCSX2 automatically — enabling a mod\n"
            "copies it to PCSX2; disabling removes it."
        )
        deploy_note.setStyleSheet("color: #7070a0; font-size: 12px;")
        deploy_note.setWordWrap(True)
        layout.addWidget(deploy_note)

        layout.addWidget(_sep())

        # ---- Wizard ----
        layout.addWidget(_section("Setup"))

        wizard_btn = QPushButton("🧙 Re-run Setup Wizard")
        wizard_btn.clicked.connect(self.rerun_wizard.emit)
        layout.addWidget(wizard_btn)

        layout.addWidget(_sep())

        # ---- Theme ----
        layout.addWidget(_section("Appearance"))

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        for key, display in THEME_KEYS.items():
            self._theme_combo.addItem(display, key)
        # Select currently active theme
        current_key = getattr(self.config, "theme", "dark")
        idx = self._theme_combo.findData(current_key)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        theme_note = QLabel("ℹ  Theme is applied immediately and saved with settings.")
        theme_note.setStyleSheet("color: #7070a0; font-size: 12px;")
        layout.addWidget(theme_note)

        layout.addWidget(_sep())

        # ---- About / Patreon ----
        layout.addWidget(_section("About"))

        about_lbl = QLabel(
            f"<b>PS2 Mod Manager</b>  v{APP_VERSION}<br>"
            "A free mod manager for PCSX2.<br><br>"
            "Manage texture packs, PNACH patches, cover art, memory cards, and cheats "
            "all in one place.<br><br>"
            f'If you enjoy this app, please consider supporting the developer on '
            f'<a href="{PATREON_URL}" style="color:#f96854;">Patreon</a>!'
        )
        about_lbl.setOpenExternalLinks(True)
        about_lbl.setWordWrap(True)
        about_lbl.setStyleSheet("color: #9090b0; font-size: 12px; line-height: 1.6;")
        layout.addWidget(about_lbl)

        patreon_btn = QPushButton("❤  Support on Patreon")
        patreon_btn.setObjectName("patreon_btn")
        patreon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        patreon_btn.clicked.connect(self._open_patreon)
        layout.addWidget(patreon_btn)

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
        self.config.partial_textures_path = self._partial_tex_chooser.get_path()
        self.config.mods_storage_path = self._storage_chooser.get_path()
        self.config.show_conflict_warnings = self._conflicts_check.isChecked()
        self.config.check_updates_on_start = self._updates_check.isChecked()
        self.config.theme = self._theme_combo.currentData() or "dark"

        save_config(self.config)
        self.settings_saved.emit(self.config)
        self.emit_status("Settings saved ✅")
        QMessageBox.information(self, "Saved", "Settings have been saved.")

    def _on_theme_changed(self, _index: int):
        """Apply the newly selected theme immediately as a live preview.

        Note: the config object is *not* updated here — the theme is only
        persisted when the user clicks "Save Settings".
        """
        from PyQt6.QtWidgets import QApplication
        theme_key = self._theme_combo.currentData() or "dark"
        app = QApplication.instance()
        if app:
            apply_theme(app, theme_key)
        self.theme_changed.emit(theme_key)

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
        self._partial_tex_chooser.set_path(paths.get("partial_textures_path", ""))

    def _open_patreon(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(PATREON_URL))

    def reload_config(self, config: AppConfig):
        """Update displayed values when config changes."""
        self.config = config
        self._pcsx2_chooser.set_path(config.pcsx2_path)
        self._tex_chooser.set_path(config.textures_path)
        self._pnach_chooser.set_path(config.pnach_path)
        self._covers_chooser.set_path(config.cover_art_path)
        self._memcards_chooser.set_path(config.memcards_path)
        self._cheats_chooser.set_path(config.cheats_path)
        self._partial_tex_chooser.set_path(config.partial_textures_path)
        self._storage_chooser.set_path(config.mods_storage_path)
        self._conflicts_check.setChecked(config.show_conflict_warnings)
        self._updates_check.setChecked(config.check_updates_on_start)
        idx = self._theme_combo.findData(getattr(config, "theme", "dark"))
        if idx >= 0:
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(idx)
            self._theme_combo.blockSignals(False)


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #b0b0d0;")
    return lbl


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    return f
