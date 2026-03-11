#!/usr/bin/env python3
"""PS2 Mod Manager — entry point."""

import sys
import os
import time

# Ensure the project root is on the Python path
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

from src.core.config_manager import load_config
from src.core.assets import icon_path, ico_path
from src.ui.main_window import MainWindow
from src.ui.theme import apply_theme


def _load_app_icon() -> QIcon:
    """Return the application icon, using available sizes for best quality."""
    icon = QIcon()
    for size in (16, 32, 48, 256):
        path = icon_path(size)
        if os.path.exists(path):
            icon.addFile(path)
    return icon


def main():
    # Enable high-DPI scaling
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("PS2 Mod Manager")
    from src import __version__
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PS2ModManager")
    app.setOrganizationDomain("ps2modmanager.github.io")

    # Set default font
    font = QFont("Segoe UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)

    # Apply dark theme
    apply_theme(app)

    # Set application icon (shows in taskbar / Alt+Tab / title bar / Windows Explorer)
    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)

    # ── Splash screen ─────────────────────────────────────────────────────
    from src.ui.splash import create_splash, destroy_splash
    splash = create_splash()
    splash.set_message("Loading configuration…", 0.1)
    app.processEvents()

    # Load configuration
    config = load_config()

    splash.set_message("Initialising mod database…", 0.35)
    app.processEvents()

    # ── Create main window ────────────────────────────────────────────────
    splash.set_message("Building interface…", 0.65)
    app.processEvents()

    window = MainWindow(config)
    window.setWindowIcon(app_icon)

    splash.set_message("Ready!", 1.0)
    app.processEvents()

    # Small pause so the user sees the "Ready!" state
    time.sleep(0.3)

    window.show()
    destroy_splash(splash)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
