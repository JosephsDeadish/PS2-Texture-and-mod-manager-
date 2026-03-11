"""Base panel class for all content panels in PS2 Mod Manager."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QLineEdit,
)


class BasePanel(QWidget):
    """Base class for all main content panels."""

    status_message = pyqtSignal(str)

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._build_header()
        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(20, 16, 20, 16)
        self._content_layout.setSpacing(12)
        self._root_layout.addLayout(self._content_layout)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("header_bar")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 0, 20, 0)

        title_lbl = QLabel(self._title)
        title_lbl.setObjectName("header_title")
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()

        if self._subtitle:
            sub_lbl = QLabel(self._subtitle)
            sub_lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
            h_layout.addWidget(sub_lbl)

        self._root_layout.addWidget(header)

    def emit_status(self, msg: str):
        self.status_message.emit(msg)

    def refresh(self):
        """Subclasses override to refresh displayed data."""
        pass
