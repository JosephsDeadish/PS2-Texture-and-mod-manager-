"""Main application window for PS2 Mod Manager."""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.core.config_manager import load_config, save_config
from src.core.mod_manager import ModDatabase, ModManager
from src.models.mod import AppConfig, ModType
from src.ui.browse_panel import BrowsePanel
from src.ui.dashboard import DashboardPanel
from src.ui.memcard_panel import MemoryCardPanel
from src.ui.mod_panel import ModPanel
from src.ui.settings_panel import SettingsPanel
from src.ui.setup_wizard import SetupWizard


# ---------------------------------------------------------------------------
# Sidebar navigation button
# ---------------------------------------------------------------------------

class NavButton(QPushButton):
    """Sidebar navigation button."""

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(f"  {icon}  {label}", parent)
        self.setObjectName("nav_btn")
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.db = ModDatabase()
        self.setWindowTitle("PS2 Mod Manager")
        self.setMinimumSize(1100, 720)
        self._nav_buttons: list[NavButton] = []
        self._build_ui()
        self._check_first_run()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- Sidebar ----
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Logo
        logo = QLabel("PS2")
        logo.setObjectName("sidebar_logo")
        sidebar_layout.addWidget(logo)

        sub = QLabel("Mod Manager")
        sub.setObjectName("sidebar_subtitle")
        sidebar_layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #0f3460; margin: 0 12px;")
        sidebar_layout.addWidget(sep)

        sidebar_layout.addSpacing(8)

        # Navigation items
        nav_items = [
            ("🏠", "Dashboard"),
            ("🎨", "Texture Packs"),
            ("🔧", "PNACH Patches"),
            ("🖼️", "Cover Art"),
            ("💾", "Memory Cards"),
            ("⚡", "Cheats"),
            ("🌐", "Browse"),
        ]

        for icon, label in nav_items:
            btn = NavButton(icon, label)
            btn.clicked.connect(self._make_nav_handler(len(self._nav_buttons)))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #0f3460; margin: 0 12px;")
        sidebar_layout.addWidget(sep2)

        # Settings button
        settings_btn = NavButton("⚙️", "Settings")
        settings_btn.clicked.connect(self._make_nav_handler(len(self._nav_buttons)))
        sidebar_layout.addWidget(settings_btn)
        self._nav_buttons.append(settings_btn)

        sidebar_layout.addSpacing(12)
        root_layout.addWidget(sidebar)

        # ---- Content stack ----
        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")
        root_layout.addWidget(self._stack, 1)

        # Pages (must match nav_items order + settings at end)
        self._dashboard = DashboardPanel(self.db, self.config)
        self._stack.addWidget(self._dashboard)

        self._texture_panel = ModPanel(ModType.TEXTURE_PACK, self.db, self.config)
        self._stack.addWidget(self._texture_panel)

        self._pnach_panel = ModPanel(ModType.PNACH, self.db, self.config)
        self._stack.addWidget(self._pnach_panel)

        self._cover_panel = ModPanel(ModType.COVER_ART, self.db, self.config)
        self._stack.addWidget(self._cover_panel)

        self._memcard_panel = MemoryCardPanel(self.config)
        self._stack.addWidget(self._memcard_panel)

        self._cheat_panel = ModPanel(ModType.CHEAT, self.db, self.config)
        self._stack.addWidget(self._cheat_panel)

        self._browse_panel = BrowsePanel(self.config)
        self._stack.addWidget(self._browse_panel)

        self._settings_panel = SettingsPanel(self.config)
        self._settings_panel.settings_saved.connect(self._on_settings_saved)
        self._settings_panel.rerun_wizard.connect(self._run_wizard)
        self._stack.addWidget(self._settings_panel)

        # Connect status messages
        for panel in (
            self._dashboard,
            self._texture_panel,
            self._pnach_panel,
            self._cover_panel,
            self._memcard_panel,
            self._cheat_panel,
            self._browse_panel,
            self._settings_panel,
        ):
            panel.status_message.connect(self._show_status)

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.showMessage("Ready")
        self.setStatusBar(self._status_bar)

        # Activate first nav button
        self._activate_nav(0)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _make_nav_handler(self, index: int):
        def _handler():
            self._activate_nav(index)
        return _handler

    def _activate_nav(self, index: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self._stack.setCurrentIndex(index)
        # Refresh the panel
        panel = self._stack.currentWidget()
        if hasattr(panel, "refresh"):
            panel.refresh()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_settings_saved(self, config: AppConfig):
        self.config = config
        self._dashboard.config = config
        self._texture_panel.config = config
        self._pnach_panel.config = config
        self._cover_panel.config = config
        self._memcard_panel.config = config
        self._cheat_panel.config = config
        self._browse_panel.config = config
        self._dashboard.refresh()

    def _show_status(self, msg: str):
        self._status_bar.showMessage(msg, 5000)

    # ------------------------------------------------------------------
    # First-run / Setup Wizard
    # ------------------------------------------------------------------

    def _check_first_run(self):
        if self.config.first_run:
            self._run_wizard()

    def _run_wizard(self):
        wizard = SetupWizard(self.config, self)
        wizard.setup_complete.connect(self._on_setup_complete)
        wizard.exec()

    def _on_setup_complete(self, config: AppConfig):
        self.config = config
        self._on_settings_saved(config)
        self._settings_panel.reload_config(config)
        self._show_status("Setup complete ✅")
