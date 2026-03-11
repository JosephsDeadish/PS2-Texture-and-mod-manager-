#!/usr/bin/env python3
"""PS2 Mod Manager — entry point."""

import sys
import os

# Ensure the project root is on the Python path
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.core.config_manager import load_config
from src.ui.main_window import MainWindow
from src.ui.theme import apply_theme


def main():
    # Enable high-DPI scaling
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("PS2 Mod Manager")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PS2ModManager")

    # Set default font
    font = QFont("Segoe UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)

    # Apply dark theme
    apply_theme(app)

    # Load configuration
    config = load_config()

    # Create and show main window
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
