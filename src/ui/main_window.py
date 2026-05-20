"""Main application window for PS2 Mod Manager."""

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QObject
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
from src.ui.downloads_panel import DownloadsPanel
from src.ui.library_panel import LibraryPanel
from src.ui.memcard_panel import MemoryCardPanel
from src.ui.mod_panel import ModPanel
from src.ui.settings_panel import SettingsPanel
from src.ui.setup_wizard import SetupWizard

PATREON_URL = "https://www.patreon.com/c/DeadOnTheInside"


# ---------------------------------------------------------------------------
# Helper: bridge object so the update checker thread can emit Qt signals
# ---------------------------------------------------------------------------

class _UpdateSignals(QObject):
    updates_found = pyqtSignal(int)   # number of mods with updates


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
        self._update_signals = _UpdateSignals()
        self._update_signals.updates_found.connect(self._on_updates_found)
        self._build_ui()
        self._check_first_run()
        self._maybe_start_update_checker()
        # Validate geometry against screen bounds so window never opens off-screen (issue #19)
        self._clamp_to_screen()

    def _clamp_to_screen(self):
        """Ensure the window is fully visible on the current screen."""
        try:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            geo = self.frameGeometry()
            # Clamp position so the window stays within the available area
            x = max(available.left(), min(geo.x(), available.right() - geo.width()))
            y = max(available.top(), min(geo.y(), available.bottom() - geo.height()))
            self.move(x, y)
        except Exception:
            pass  # Never crash startup due to geometry calculation

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
            ("🌐", "Discover"),
            ("🎮", "My Library"),
            ("📥", "Downloads"),
            ("🎨", "Texture Packs"),
            ("🔧", "PNACH Codes & Cheats"),
            ("🖼️", "Cover Art"),
            ("💾", "Memory Cards"),
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

        # Patreon support banner
        patreon_btn = QPushButton("❤  Support on Patreon")
        patreon_btn.setObjectName("patreon_btn")
        patreon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        patreon_btn.setToolTip(PATREON_URL)
        patreon_btn.clicked.connect(self._open_patreon)
        sidebar_layout.addWidget(patreon_btn)

        sidebar_layout.addSpacing(4)

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
        self._stack.addWidget(self._dashboard)          # index 0

        self._browse_panel = BrowsePanel(self.config)
        self._browse_panel.set_db(self.db)
        self._browse_panel.mod_installed.connect(self._on_mod_installed)
        self._stack.addWidget(self._browse_panel)       # index 1

        self._library_panel = LibraryPanel(self.db, self.config)
        self._library_panel.browse_game.connect(self._on_library_browse_game)
        self._stack.addWidget(self._library_panel)      # index 2

        self._downloads_panel = DownloadsPanel(self.config)
        self._stack.addWidget(self._downloads_panel)    # index 3

        self._texture_panel = ModPanel(ModType.TEXTURE_PACK, self.db, self.config)
        self._stack.addWidget(self._texture_panel)      # index 4

        self._pnach_panel = ModPanel(ModType.PNACH, self.db, self.config,
                                      extra_types=[ModType.CHEAT])
        self._stack.addWidget(self._pnach_panel)        # index 5

        self._cover_panel = ModPanel(ModType.COVER_ART, self.db, self.config)
        self._stack.addWidget(self._cover_panel)        # index 6

        self._memcard_panel = MemoryCardPanel(self.config)
        self._stack.addWidget(self._memcard_panel)      # index 7

        self._settings_panel = SettingsPanel(self.config)
        self._settings_panel.settings_saved.connect(self._on_settings_saved)
        self._settings_panel.rerun_wizard.connect(self._run_wizard)
        self._stack.addWidget(self._settings_panel)     # index 8

        # Wire cross-panel "see more by author" navigation
        _panel_nav_index = {
            ModType.TEXTURE_PACK: 4,
            ModType.PNACH: 5,
            ModType.COVER_ART: 6,
            ModType.CHEAT: 5,   # merged into PNACH panel
        }
        for panel in (
            self._texture_panel,
            self._pnach_panel,
            self._cover_panel,
        ):
            panel.navigate_to_author_type.connect(
                lambda author, mod_type, _nav=_panel_nav_index: self._navigate_to_author_type(
                    author, mod_type, _nav
                )
            )

        # Connect status messages
        for panel in (
            self._dashboard,
            self._texture_panel,
            self._pnach_panel,
            self._cover_panel,
            self._memcard_panel,
            self._browse_panel,
            self._library_panel,
            self._downloads_panel,
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

    def _navigate_to_author_type(self, author: str, mod_type, nav_index: dict):
        """Navigate to the target mod panel and pre-filter by *author*."""
        idx = nav_index.get(mod_type)
        if idx is None:
            return
        self._activate_nav(idx)
        # Get the now-active panel and apply the author filter
        panel = self._stack.currentWidget()
        if hasattr(panel, "_filter_by_author"):
            panel._filter_by_author(author)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_mod_installed(self):
        """Refresh all mod panels after a mod is installed from the Discover panel."""
        for panel in (
            self._texture_panel,
            self._pnach_panel,
            self._cover_panel,
        ):
            try:
                panel._apply_filter()
            except Exception:
                pass  # Never crash the UI if a panel isn't ready
        try:
            self._library_panel.refresh()
        except Exception:
            pass  # Never crash the UI if the library panel isn't ready

    def _on_library_browse_game(self, serial: str):
        """Navigate to the Discover panel and pre-filter by *serial*."""
        self._activate_nav(1)  # Discover is at index 1
        if hasattr(self._browse_panel, "filter_by_serial"):
            self._browse_panel.filter_by_serial(serial)
        self._show_status(f"Browsing catalogue for {serial}")

    def _on_settings_saved(self, config: AppConfig):
        self.config = config
        self._dashboard.config = config
        self._texture_panel.config = config
        self._pnach_panel.config = config
        self._cover_panel.config = config
        self._memcard_panel.config = config
        self._browse_panel.config = config
        self._library_panel.config = config
        self._downloads_panel.config = config
        self._dashboard.refresh()

    def _show_status(self, msg: str):
        self._status_bar.showMessage(msg, 5000)

    def _open_patreon(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(PATREON_URL))

    # ------------------------------------------------------------------
    # First-run / Setup Wizard
    # ------------------------------------------------------------------

    def _check_first_run(self):
        if self.config.first_run:
            self._run_wizard()

    def _run_wizard(self):
        parent = self if self.isVisible() else None
        wizard = SetupWizard(self.config, parent)
        wizard.setup_complete.connect(self._on_setup_complete)
        wizard.exec()

    def _on_setup_complete(self, config: AppConfig):
        self.config = config
        self._on_settings_saved(config)
        self._settings_panel.reload_config(config)
        self._show_status("Setup complete ✅")

    # ------------------------------------------------------------------
    # Update checker
    # ------------------------------------------------------------------

    def _maybe_start_update_checker(self):
        if not self.config.check_updates_on_start:
            return
        try:
            from src.core.updater import UpdateChecker
            self._update_checker = UpdateChecker(self.db)
            self._update_checker.start(
                on_complete=self._update_signals.updates_found.emit
            )
        except Exception:
            pass  # Never crash the UI over an update check

    def _on_updates_found(self, count: int):
        if count > 0:
            self._status_bar.showMessage(
                f"🔔 {count} mod update(s) available — check individual mod panels for details",
                10_000,
            )
            # Refresh all mod panels so "↑ Update" badges appear immediately
            for panel in (
                self._texture_panel,
                self._pnach_panel,
                self._cover_panel,
            ):
                try:
                    panel._apply_filter()
                except Exception:
                    pass
            try:
                self._library_panel.refresh()
            except Exception:
                pass
