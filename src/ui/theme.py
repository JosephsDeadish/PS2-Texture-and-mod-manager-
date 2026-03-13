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

QFrame#mod_item_shadowed {
    background-color: #14161e;
    border-radius: 8px;
    border: 1px solid #303050;
    padding: 8px;
    margin: 3px 0px;
    opacity: 0.6;
}

QFrame#mod_item_shadowed:hover {
    border: 1px solid #505080;
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

/* ===== Patreon button ===== */
QPushButton#patreon_btn {
    background-color: #f96854;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 8px;
    font-size: 12px;
}

QPushButton#patreon_btn:hover {
    background-color: #ff8070;
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

# ---------------------------------------------------------------------------
# Midnight theme — deep dark with cyan/teal accent
# ---------------------------------------------------------------------------

MIDNIGHT_THEME = """
/* ===== Global ===== */
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #010409;
}

/* ===== Sidebar ===== */
#sidebar {
    background-color: #161b22;
    border-right: 1px solid #21262d;
    min-width: 220px;
    max-width: 220px;
}

#sidebar_logo {
    color: #00b8d4;
    font-size: 20px;
    font-weight: bold;
    padding: 20px 16px 8px 16px;
    letter-spacing: 1px;
}

#sidebar_subtitle {
    color: #8b949e;
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}

QPushButton#nav_btn {
    text-align: left;
    padding: 12px 16px;
    border: none;
    border-radius: 6px;
    background-color: transparent;
    color: #8b949e;
    font-size: 13px;
    margin: 2px 8px;
}

QPushButton#nav_btn:hover {
    background-color: #21262d;
    color: #c9d1d9;
}

QPushButton#nav_btn:checked {
    background-color: #00b8d4;
    color: #010409;
    font-weight: bold;
}

/* ===== Content area ===== */
#content_area {
    background-color: #0d1117;
}

/* ===== Cards ===== */
QFrame#card {
    background-color: #161b22;
    border-radius: 10px;
    border: 1px solid #21262d;
    padding: 12px;
}

/* ===== Mod list item ===== */
QFrame#mod_item {
    background-color: #1c2128;
    border-radius: 8px;
    border: 1px solid #30363d;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item:hover {
    border: 1px solid #00b8d4;
}

QFrame#mod_item_conflict {
    background-color: #2d1b1b;
    border-radius: 8px;
    border: 1px solid #f85149;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed {
    background-color: #0d1117;
    border-radius: 8px;
    border: 1px solid #21262d;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed:hover {
    border: 1px solid #30363d;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #30363d;
}

QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#primary_btn {
    background-color: #00b8d4;
    color: #010409;
    font-weight: bold;
}

QPushButton#primary_btn:hover {
    background-color: #26c6da;
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
    background-color: #21262d;
    color: #484f58;
}

/* ===== Toggle switch ===== */
QCheckBox {
    color: #c9d1d9;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 40px;
    height: 22px;
    border-radius: 11px;
    background-color: #21262d;
    border: 2px solid #30363d;
}

QCheckBox::indicator:checked {
    background-color: #00b8d4;
    border: 2px solid #00b8d4;
}

/* ===== Labels ===== */
QLabel#section_title {
    font-size: 22px;
    font-weight: bold;
    color: #f0f6fc;
    padding: 8px 0px 4px 0px;
}

QLabel#section_subtitle {
    font-size: 13px;
    color: #8b949e;
    padding-bottom: 8px;
}

QLabel#badge {
    background-color: #00b8d4;
    color: #010409;
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
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #00b8d4;
}

QLineEdit:focus {
    border: 1px solid #00b8d4;
}

QTextEdit {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px;
}

/* ===== Combo boxes ===== */
QComboBox {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 12px;
    min-width: 120px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #21262d;
    selection-background-color: #00b8d4;
    selection-color: #010409;
}

/* ===== Scroll bars ===== */
QScrollBar:vertical {
    background: #010409;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #00b8d4;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #010409;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #00b8d4;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Progress bar ===== */
QProgressBar {
    background-color: #0d1117;
    border-radius: 6px;
    border: 1px solid #30363d;
    text-align: center;
    color: white;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #00b8d4;
    border-radius: 5px;
}

/* ===== Tab widget ===== */
QTabWidget::pane {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #0d1117;
    color: #8b949e;
    padding: 8px 20px;
    border: none;
    border-radius: 6px 6px 0 0;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #00b8d4;
    color: #010409;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background-color: #21262d;
    color: #c9d1d9;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #21262d;
    width: 2px;
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #00b8d4;
    padding: 6px;
    border-radius: 4px;
}

/* ===== Dialog ===== */
QDialog {
    background-color: #0d1117;
}

/* ===== Message box ===== */
QMessageBox {
    background-color: #0d1117;
}

/* ===== Slider ===== */
QSlider::groove:horizontal {
    background: #0d1117;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #00b8d4;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -5px 0;
}

QSlider::sub-page:horizontal {
    background: #00b8d4;
    border-radius: 3px;
}

/* ===== Patreon button ===== */
QPushButton#patreon_btn {
    background-color: #f96854;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 8px;
    font-size: 12px;
}

QPushButton#patreon_btn:hover {
    background-color: #ff8070;
}

/* ===== Separator ===== */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #21262d;
}

/* ===== Group box ===== */
QGroupBox {
    border: 1px solid #30363d;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 8px;
    color: #8b949e;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #c9d1d9;
}

/* ===== Header bar ===== */
#header_bar {
    background-color: #161b22;
    border-bottom: 1px solid #21262d;
    min-height: 56px;
    max-height: 56px;
    padding: 0px 16px;
}

#header_title {
    font-size: 18px;
    font-weight: bold;
    color: #f0f6fc;
}

/* ===== Status bar ===== */
QStatusBar {
    background-color: #010409;
    color: #8b949e;
    border-top: 1px solid #21262d;
}

/* ===== Search bar ===== */
#search_bar {
    background-color: #0d1117;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 18px;
    padding: 6px 14px 6px 36px;
    font-size: 13px;
}

#search_bar:focus {
    border: 1px solid #00b8d4;
}
"""

# ---------------------------------------------------------------------------
# Retro Green theme — dark with neon green accent
# ---------------------------------------------------------------------------

RETRO_GREEN_THEME = """
/* ===== Global ===== */
QWidget {
    background-color: #0a0e0a;
    color: #b0ffb0;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #050805;
}

/* ===== Sidebar ===== */
#sidebar {
    background-color: #0d120d;
    border-right: 1px solid #1a2e1a;
    min-width: 220px;
    max-width: 220px;
}

#sidebar_logo {
    color: #4caf50;
    font-size: 20px;
    font-weight: bold;
    padding: 20px 16px 8px 16px;
    letter-spacing: 1px;
}

#sidebar_subtitle {
    color: #5a8a5a;
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}

QPushButton#nav_btn {
    text-align: left;
    padding: 12px 16px;
    border: none;
    border-radius: 6px;
    background-color: transparent;
    color: #6a9a6a;
    font-size: 13px;
    margin: 2px 8px;
}

QPushButton#nav_btn:hover {
    background-color: #1a2e1a;
    color: #b0ffb0;
}

QPushButton#nav_btn:checked {
    background-color: #4caf50;
    color: #050805;
    font-weight: bold;
}

/* ===== Content area ===== */
#content_area {
    background-color: #0a0e0a;
}

/* ===== Cards ===== */
QFrame#card {
    background-color: #0d120d;
    border-radius: 10px;
    border: 1px solid #1a2e1a;
    padding: 12px;
}

/* ===== Mod list item ===== */
QFrame#mod_item {
    background-color: #101510;
    border-radius: 8px;
    border: 1px solid #1e301e;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item:hover {
    border: 1px solid #4caf50;
}

QFrame#mod_item_conflict {
    background-color: #1a0d0d;
    border-radius: 8px;
    border: 1px solid #e94560;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed {
    background-color: #050805;
    border-radius: 8px;
    border: 1px solid #1a2e1a;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed:hover {
    border: 1px solid #2a4a2a;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #1a2e1a;
    color: #b0ffb0;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #243a24;
}

QPushButton:pressed {
    background-color: #0d120d;
}

QPushButton#primary_btn {
    background-color: #4caf50;
    color: #050805;
    font-weight: bold;
}

QPushButton#primary_btn:hover {
    background-color: #66bb6a;
}

QPushButton#danger_btn {
    background-color: #8b0000;
    color: #ffffff;
}

QPushButton#danger_btn:hover {
    background-color: #c00000;
}

QPushButton#success_btn {
    background-color: #4caf50;
    color: #050805;
}

QPushButton#success_btn:hover {
    background-color: #66bb6a;
}

QPushButton:disabled {
    background-color: #1a1e1a;
    color: #3a4e3a;
}

/* ===== Toggle switch ===== */
QCheckBox {
    color: #b0ffb0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 40px;
    height: 22px;
    border-radius: 11px;
    background-color: #1a2e1a;
    border: 2px solid #2a4a2a;
}

QCheckBox::indicator:checked {
    background-color: #4caf50;
    border: 2px solid #4caf50;
}

/* ===== Labels ===== */
QLabel#section_title {
    font-size: 22px;
    font-weight: bold;
    color: #e0ffe0;
    padding: 8px 0px 4px 0px;
}

QLabel#section_subtitle {
    font-size: 13px;
    color: #5a8a5a;
    padding-bottom: 8px;
}

QLabel#badge {
    background-color: #4caf50;
    color: #050805;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}

QLabel#badge_success {
    background-color: #2e7d32;
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
    background-color: #070b07;
    color: #b0ffb0;
    border: 1px solid #1a2e1a;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #4caf50;
}

QLineEdit:focus {
    border: 1px solid #4caf50;
}

QTextEdit {
    background-color: #070b07;
    color: #b0ffb0;
    border: 1px solid #1a2e1a;
    border-radius: 6px;
    padding: 8px;
}

/* ===== Combo boxes ===== */
QComboBox {
    background-color: #1a2e1a;
    color: #b0ffb0;
    border: 1px solid #2a4a2a;
    border-radius: 6px;
    padding: 6px 12px;
    min-width: 120px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #0d120d;
    color: #b0ffb0;
    border: 1px solid #1a2e1a;
    selection-background-color: #4caf50;
    selection-color: #050805;
}

/* ===== Scroll bars ===== */
QScrollBar:vertical {
    background: #050805;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #1a2e1a;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #4caf50;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #050805;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #1a2e1a;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #4caf50;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Progress bar ===== */
QProgressBar {
    background-color: #070b07;
    border-radius: 6px;
    border: 1px solid #1a2e1a;
    text-align: center;
    color: #b0ffb0;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #4caf50;
    border-radius: 5px;
}

/* ===== Tab widget ===== */
QTabWidget::pane {
    background-color: #0d120d;
    border: 1px solid #1a2e1a;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #070b07;
    color: #5a8a5a;
    padding: 8px 20px;
    border: none;
    border-radius: 6px 6px 0 0;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #4caf50;
    color: #050805;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background-color: #1a2e1a;
    color: #b0ffb0;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #1a2e1a;
    width: 2px;
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #0d120d;
    color: #b0ffb0;
    border: 1px solid #4caf50;
    padding: 6px;
    border-radius: 4px;
}

/* ===== Dialog ===== */
QDialog {
    background-color: #0a0e0a;
}

/* ===== Message box ===== */
QMessageBox {
    background-color: #0a0e0a;
}

/* ===== Slider ===== */
QSlider::groove:horizontal {
    background: #070b07;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #4caf50;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -5px 0;
}

QSlider::sub-page:horizontal {
    background: #4caf50;
    border-radius: 3px;
}

/* ===== Patreon button ===== */
QPushButton#patreon_btn {
    background-color: #f96854;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 8px;
    font-size: 12px;
}

QPushButton#patreon_btn:hover {
    background-color: #ff8070;
}

/* ===== Separator ===== */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #1a2e1a;
}

/* ===== Group box ===== */
QGroupBox {
    border: 1px solid #1a2e1a;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 8px;
    color: #5a8a5a;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #7aaa7a;
}

/* ===== Header bar ===== */
#header_bar {
    background-color: #0d120d;
    border-bottom: 1px solid #1a2e1a;
    min-height: 56px;
    max-height: 56px;
    padding: 0px 16px;
}

#header_title {
    font-size: 18px;
    font-weight: bold;
    color: #e0ffe0;
}

/* ===== Status bar ===== */
QStatusBar {
    background-color: #050805;
    color: #5a8a5a;
    border-top: 1px solid #1a2e1a;
}

/* ===== Search bar ===== */
#search_bar {
    background-color: #070b07;
    color: #b0ffb0;
    border: 1px solid #1a2e1a;
    border-radius: 18px;
    padding: 6px 14px 6px 36px;
    font-size: 13px;
}

#search_bar:focus {
    border: 1px solid #4caf50;
}
"""

# ---------------------------------------------------------------------------
# Purple theme — dark with deep purple/violet accent
# ---------------------------------------------------------------------------

PURPLE_THEME = """
/* ===== Global ===== */
QWidget {
    background-color: #120d1a;
    color: #e0d0f0;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #0a0710;
}

/* ===== Sidebar ===== */
#sidebar {
    background-color: #180d24;
    border-right: 1px solid #2d1a45;
    min-width: 220px;
    max-width: 220px;
}

#sidebar_logo {
    color: #9c27b0;
    font-size: 20px;
    font-weight: bold;
    padding: 20px 16px 8px 16px;
    letter-spacing: 1px;
}

#sidebar_subtitle {
    color: #7a5a8a;
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}

QPushButton#nav_btn {
    text-align: left;
    padding: 12px 16px;
    border: none;
    border-radius: 6px;
    background-color: transparent;
    color: #8a6a9a;
    font-size: 13px;
    margin: 2px 8px;
}

QPushButton#nav_btn:hover {
    background-color: #2d1a45;
    color: #e0d0f0;
}

QPushButton#nav_btn:checked {
    background-color: #9c27b0;
    color: #ffffff;
    font-weight: bold;
}

/* ===== Content area ===== */
#content_area {
    background-color: #120d1a;
}

/* ===== Cards ===== */
QFrame#card {
    background-color: #180d24;
    border-radius: 10px;
    border: 1px solid #2d1a45;
    padding: 12px;
}

/* ===== Mod list item ===== */
QFrame#mod_item {
    background-color: #1e1228;
    border-radius: 8px;
    border: 1px solid #3d2255;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item:hover {
    border: 1px solid #9c27b0;
}

QFrame#mod_item_conflict {
    background-color: #2a0d1a;
    border-radius: 8px;
    border: 1px solid #e94560;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed {
    background-color: #0a0710;
    border-radius: 8px;
    border: 1px solid #2d1a45;
    padding: 8px;
    margin: 3px 0px;
}

QFrame#mod_item_shadowed:hover {
    border: 1px solid #4d2a65;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #2d1a45;
    color: #e0d0f0;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #3d2255;
}

QPushButton:pressed {
    background-color: #180d24;
}

QPushButton#primary_btn {
    background-color: #9c27b0;
    color: #ffffff;
    font-weight: bold;
}

QPushButton#primary_btn:hover {
    background-color: #ab47bc;
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
    background-color: #2a1a35;
    color: #4a3a5a;
}

/* ===== Toggle switch ===== */
QCheckBox {
    color: #e0d0f0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 40px;
    height: 22px;
    border-radius: 11px;
    background-color: #2d1a45;
    border: 2px solid #3d2255;
}

QCheckBox::indicator:checked {
    background-color: #9c27b0;
    border: 2px solid #9c27b0;
}

/* ===== Labels ===== */
QLabel#section_title {
    font-size: 22px;
    font-weight: bold;
    color: #f0e0ff;
    padding: 8px 0px 4px 0px;
}

QLabel#section_subtitle {
    font-size: 13px;
    color: #7a5a8a;
    padding-bottom: 8px;
}

QLabel#badge {
    background-color: #9c27b0;
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
    background-color: #0e0918;
    color: #e0d0f0;
    border: 1px solid #3d2255;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #9c27b0;
}

QLineEdit:focus {
    border: 1px solid #9c27b0;
}

QTextEdit {
    background-color: #0e0918;
    color: #e0d0f0;
    border: 1px solid #3d2255;
    border-radius: 6px;
    padding: 8px;
}

/* ===== Combo boxes ===== */
QComboBox {
    background-color: #2d1a45;
    color: #e0d0f0;
    border: 1px solid #3d2255;
    border-radius: 6px;
    padding: 6px 12px;
    min-width: 120px;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #180d24;
    color: #e0d0f0;
    border: 1px solid #2d1a45;
    selection-background-color: #9c27b0;
    selection-color: white;
}

/* ===== Scroll bars ===== */
QScrollBar:vertical {
    background: #0a0710;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3d2255;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #9c27b0;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #0a0710;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #3d2255;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #9c27b0;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Progress bar ===== */
QProgressBar {
    background-color: #0e0918;
    border-radius: 6px;
    border: 1px solid #3d2255;
    text-align: center;
    color: white;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #9c27b0;
    border-radius: 5px;
}

/* ===== Tab widget ===== */
QTabWidget::pane {
    background-color: #180d24;
    border: 1px solid #2d1a45;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #0e0918;
    color: #7a5a8a;
    padding: 8px 20px;
    border: none;
    border-radius: 6px 6px 0 0;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #9c27b0;
    color: white;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background-color: #2d1a45;
    color: #e0d0f0;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #2d1a45;
    width: 2px;
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #180d24;
    color: #e0d0f0;
    border: 1px solid #9c27b0;
    padding: 6px;
    border-radius: 4px;
}

/* ===== Dialog ===== */
QDialog {
    background-color: #120d1a;
}

/* ===== Message box ===== */
QMessageBox {
    background-color: #120d1a;
}

/* ===== Slider ===== */
QSlider::groove:horizontal {
    background: #0e0918;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #9c27b0;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -5px 0;
}

QSlider::sub-page:horizontal {
    background: #9c27b0;
    border-radius: 3px;
}

/* ===== Patreon button ===== */
QPushButton#patreon_btn {
    background-color: #f96854;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 4px 8px;
    font-size: 12px;
}

QPushButton#patreon_btn:hover {
    background-color: #ff8070;
}

/* ===== Separator ===== */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #2d1a45;
}

/* ===== Group box ===== */
QGroupBox {
    border: 1px solid #3d2255;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 8px;
    color: #7a5a8a;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #a070c0;
}

/* ===== Header bar ===== */
#header_bar {
    background-color: #180d24;
    border-bottom: 1px solid #2d1a45;
    min-height: 56px;
    max-height: 56px;
    padding: 0px 16px;
}

#header_title {
    font-size: 18px;
    font-weight: bold;
    color: #f0e0ff;
}

/* ===== Status bar ===== */
QStatusBar {
    background-color: #0a0710;
    color: #7a5a8a;
    border-top: 1px solid #2d1a45;
}

/* ===== Search bar ===== */
#search_bar {
    background-color: #0e0918;
    color: #e0d0f0;
    border: 1px solid #3d2255;
    border-radius: 18px;
    padding: 6px 14px 6px 36px;
    font-size: 13px;
}

#search_bar:focus {
    border: 1px solid #9c27b0;
}
"""

# ---------------------------------------------------------------------------
# Theme registry and helpers
# ---------------------------------------------------------------------------

#: Map of display name → stylesheet string for all available themes.
THEMES = {
    "Dark":         DARK_THEME,
    "Midnight":     MIDNIGHT_THEME,
    "Retro Green":  RETRO_GREEN_THEME,
    "Purple":       PURPLE_THEME,
}

#: Internal config key → display name mapping (lowercase keys stored in config).
THEME_KEYS = {
    "dark":         "Dark",
    "midnight":     "Midnight",
    "retro_green":  "Retro Green",
    "purple":       "Purple",
}


def get_stylesheet(theme_key: str) -> str:
    """Return the stylesheet string for *theme_key* (e.g. ``"dark"``).

    Falls back to the dark theme if *theme_key* is not recognised.
    """
    display_name = THEME_KEYS.get(theme_key, "Dark")
    return THEMES.get(display_name, DARK_THEME)


def apply_theme(app, theme_key: str = "dark"):
    """Apply the named theme to *app* (a :class:`QApplication`).

    Parameters
    ----------
    app:
        The ``QApplication`` instance.
    theme_key:
        The theme identifier stored in :class:`~src.models.mod.AppConfig`.
        Defaults to ``"dark"`` for backward compatibility.
    """
    app.setStyleSheet(get_stylesheet(theme_key))
