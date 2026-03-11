"""Dark theme stylesheet for PS2 Mod Manager."""

DARK_THEME = """
/* ===== Global ===== */
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #0f0f1a;
}

/* ===== Sidebar ===== */
#sidebar {
    background-color: #16213e;
    border-right: 1px solid #0f3460;
    min-width: 220px;
    max-width: 220px;
}

#sidebar_logo {
    color: #e94560;
    font-size: 20px;
    font-weight: bold;
    padding: 20px 16px 8px 16px;
    letter-spacing: 1px;
}

#sidebar_subtitle {
    color: #9e9e9e;
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}

QPushButton#nav_btn {
    text-align: left;
    padding: 12px 16px;
    border: none;
    border-radius: 6px;
    background-color: transparent;
    color: #b0b0c0;
    font-size: 13px;
    margin: 2px 8px;
}

QPushButton#nav_btn:hover {
    background-color: #0f3460;
    color: #ffffff;
}

QPushButton#nav_btn:checked {
    background-color: #e94560;
    color: #ffffff;
    font-weight: bold;
}

/* ===== Content area ===== */
#content_area {
    background-color: #1a1a2e;
}

/* ===== Cards ===== */
QFrame#card {
    background-color: #16213e;
    border-radius: 10px;
    border: 1px solid #0f3460;
    padding: 12px;
}

/* ===== Mod list item ===== */
QFrame#mod_item {
    background-color: #1e2440;
    border-radius: 8px;
    border: 1px solid #2a2d5a;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item:hover {
    border: 1px solid #e94560;
}

QFrame#mod_item_conflict {
    background-color: #2a1a1a;
    border-radius: 8px;
    border: 1px solid #e94560;
    padding: 8px;
    margin: 3px 0px;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #0f3460;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #1a4a8a;
}

QPushButton:pressed {
    background-color: #0a2040;
}

QPushButton#primary_btn {
    background-color: #e94560;
    color: #ffffff;
    font-weight: bold;
}

QPushButton#primary_btn:hover {
    background-color: #ff6080;
}

QPushButton#danger_btn {
    background-color: #8b0000;
    color: #ffffff;
}

QPushButton#danger_btn:hover {
    background-color: #c00000;
}

QPushButton#success_btn {
    background-color: #1a6b4a;
    color: #ffffff;
}

QPushButton#success_btn:hover {
    background-color: #22885e;
}

QPushButton:disabled {
    background-color: #333355;
    color: #666680;
}

/* ===== Toggle switch (QCheckBox as toggle) ===== */
QCheckBox {
    color: #e0e0e0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 40px;
    height: 22px;
    border-radius: 11px;
    background-color: #333355;
    border: 2px solid #555577;
}

QCheckBox::indicator:checked {
    background-color: #e94560;
    border: 2px solid #e94560;
}

/* ===== Labels ===== */
QLabel#section_title {
    font-size: 22px;
    font-weight: bold;
    color: #ffffff;
    padding: 8px 0px 4px 0px;
}

QLabel#section_subtitle {
    font-size: 13px;
    color: #9090b0;
    padding-bottom: 8px;
}

QLabel#badge {
    background-color: #e94560;
    color: white;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}

QLabel#badge_success {
    background-color: #1a6b4a;
    color: white;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
}

QLabel#badge_warning {
    background-color: #7a5500;
    color: #ffcc00;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
}

/* ===== Text inputs ===== */
QLineEdit {
    background-color: #0f1830;
    color: #e0e0e0;
    border: 1px solid #2a3060;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #e94560;
}

QLineEdit:focus {
    border: 1px solid #e94560;
}

QTextEdit {
    background-color: #0f1830;
    color: #e0e0e0;
    border: 1px solid #2a3060;
    border-radius: 6px;
    padding: 8px;
}

/* ===== Combo boxes ===== */
QComboBox {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #2a3060;
    border-radius: 6px;
    padding: 6px 12px;
    min-width: 120px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    selection-background-color: #e94560;
    selection-color: white;
}

/* ===== Scroll bars ===== */
QScrollBar:vertical {
    background: #0f0f1a;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #2a3060;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #e94560;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #0f0f1a;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #2a3060;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #e94560;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Progress bar ===== */
QProgressBar {
    background-color: #0f1830;
    border-radius: 6px;
    border: 1px solid #2a3060;
    text-align: center;
    color: white;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #e94560;
    border-radius: 5px;
}

/* ===== Tab widget ===== */
QTabWidget::pane {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #0f1830;
    color: #9090b0;
    padding: 8px 20px;
    border: none;
    border-radius: 6px 6px 0 0;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #e94560;
    color: white;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background-color: #1a2050;
    color: white;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #0f3460;
    width: 2px;
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #e94560;
    padding: 6px;
    border-radius: 4px;
}

/* ===== Dialog ===== */
QDialog {
    background-color: #1a1a2e;
}

/* ===== Message box ===== */
QMessageBox {
    background-color: #1a1a2e;
}

/* ===== Slider ===== */
QSlider::groove:horizontal {
    background: #0f1830;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #e94560;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -5px 0;
}

QSlider::sub-page:horizontal {
    background: #e94560;
    border-radius: 3px;
}

/* ===== Separator ===== */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #2a3060;
}

/* ===== Group box ===== */
QGroupBox {
    border: 1px solid #2a3060;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 8px;
    color: #9090b0;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #b0b0d0;
}

/* ===== Header bar ===== */
#header_bar {
    background-color: #16213e;
    border-bottom: 1px solid #0f3460;
    min-height: 56px;
    max-height: 56px;
    padding: 0px 16px;
}

#header_title {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
}

/* ===== Status bar ===== */
QStatusBar {
    background-color: #0f0f1a;
    color: #9090b0;
    border-top: 1px solid #2a3060;
}

/* ===== Search bar ===== */
#search_bar {
    background-color: #0f1830;
    color: #e0e0e0;
    border: 1px solid #2a3060;
    border-radius: 18px;
    padding: 6px 14px 6px 36px;
    font-size: 13px;
}

#search_bar:focus {
    border: 1px solid #e94560;
}
"""


def apply_theme(app):
    """Apply the dark theme to a QApplication."""
    app.setStyleSheet(DARK_THEME)
