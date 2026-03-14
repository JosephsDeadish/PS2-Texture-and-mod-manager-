"""Downloads panel — active downloads and history.

Shows currently in-progress downloads with progress indicators, and an
inline download-history log that was previously only accessible as a
pop-up dialog from the Browse panel.
"""

from __future__ import annotations

import threading as _threading
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel


# ---------------------------------------------------------------------------
# Single active-download row widget
# ---------------------------------------------------------------------------

class _ActiveDownloadRow(QWidget):
    """A single row showing the name and progress of an in-flight download."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QProgressBar
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet("color: #c0c0e0;")
        layout.addWidget(self._name_lbl, 1)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate by default
        self._bar.setMaximumWidth(200)
        self._bar.setFixedHeight(14)
        layout.addWidget(self._bar)

    def set_progress(self, received: int, total: int):
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(received)
        else:
            self._bar.setRange(0, 0)

    def set_done(self):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)


# ---------------------------------------------------------------------------
# Singleton registry of active downloads (app-wide, used by browse_panel too)
# ---------------------------------------------------------------------------


class ActiveDownloads:
    """Lightweight app-wide registry for in-progress downloads.

    Browse panel code calls :meth:`register` when a download starts and
    :meth:`finish` when it completes.  The :class:`DownloadsPanel` polls
    this registry to populate the "Active" section.
    """

    _entries: dict[str, dict] = {}
    _lock = _threading.Lock()

    @classmethod
    def register(cls, download_id: str, name: str) -> None:
        with cls._lock:
            cls._entries[download_id] = {"name": name, "received": 0, "total": 0}

    @classmethod
    def update(cls, download_id: str, received: int, total: int) -> None:
        with cls._lock:
            if download_id in cls._entries:
                cls._entries[download_id]["received"] = received
                cls._entries[download_id]["total"] = total

    @classmethod
    def finish(cls, download_id: str) -> None:
        with cls._lock:
            cls._entries.pop(download_id, None)

    @classmethod
    def all(cls) -> list[dict]:
        with cls._lock:
            return list(cls._entries.values())

    @classmethod
    def count(cls) -> int:
        with cls._lock:
            return len(cls._entries)


# ---------------------------------------------------------------------------
# Downloads panel
# ---------------------------------------------------------------------------

class DownloadsPanel(BasePanel):
    """Full-page panel for active downloads and download history."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("📥  Downloads", "Active downloads and installation history", parent)
        self.config = config
        self._history_entries: list = []
        self._build()
        # Poll active downloads when the panel is visible
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._refresh_active)

    def showEvent(self, event):
        super().showEvent(event)
        self._poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        content = self._content_layout

        # ── Active downloads section ──────────────────────────────────────
        active_hdr = QLabel("⬇  Active Downloads")
        active_hdr.setStyleSheet("font-weight: bold; font-size: 13px; color: #a0a0d0;")
        content.addWidget(active_hdr)

        self._active_container = QWidget()
        self._active_layout = QVBoxLayout(self._active_container)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(2)

        self._active_placeholder = QLabel("No downloads in progress.")
        self._active_placeholder.setStyleSheet("color: #50507a; font-size: 12px;")
        self._active_layout.addWidget(self._active_placeholder)

        content.addWidget(self._active_container)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1a1a3a;")
        content.addWidget(sep)

        # ── History section ───────────────────────────────────────────────
        hist_hdr = QLabel("📋  Download History")
        hist_hdr.setStyleSheet("font-weight: bold; font-size: 13px; color: #a0a0d0;")
        content.addWidget(hist_hdr)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Status:"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["All", "✅ Success", "❌ Failed", "⏭ Skipped"])
        self._status_combo.currentIndexChanged.connect(self._refresh_history)
        filter_row.addWidget(self._status_combo)

        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "All", "🎨 Texture Pack", "🔧 PNACH Patch",
            "🖼 Cover Art", "💾 Game Save", "🕹 Cheat", "📦 Other",
        ])
        self._type_combo.currentIndexChanged.connect(self._refresh_history)
        filter_row.addWidget(self._type_combo)

        filter_row.addWidget(QLabel("Serial:"))
        self._serial_edit = QLineEdit()
        self._serial_edit.setPlaceholderText("e.g. SLUS-20228")
        self._serial_edit.setMaximumWidth(130)
        self._serial_edit.textChanged.connect(self._refresh_history)
        filter_row.addWidget(self._serial_edit)

        refresh_hist_btn = QPushButton("🔄 Refresh")
        refresh_hist_btn.setToolTip("Reload the history log from disk")
        refresh_hist_btn.clicked.connect(self._refresh_history)
        filter_row.addWidget(refresh_hist_btn)

        filter_row.addStretch()
        content.addLayout(filter_row)

        # Splitter: list (left) | detail (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list_widget)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self._detail_label = QLabel("← Select an entry to see details")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_label.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self._detail_label, 1)

        right_sep = QFrame()
        right_sep.setFrameShape(QFrame.Shape.HLine)
        rl.addWidget(right_sep)

        btn_row = QHBoxLayout()
        self._delete_btn = QPushButton("🗑  Delete Entry")
        self._delete_btn.setToolTip("Remove this entry from the history log")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_entry)
        btn_row.addWidget(self._delete_btn)
        btn_row.addStretch()
        rl.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        content.addWidget(splitter, 1)

        # Bottom actions
        bottom_row = QHBoxLayout()
        clear_btn = QPushButton("🗑  Clear All History")
        clear_btn.setToolTip("Permanently delete every entry in the history log")
        clear_btn.clicked.connect(self._on_clear)
        bottom_row.addWidget(clear_btn)

        export_btn = QPushButton("📤 Export CSV")
        export_btn.setToolTip("Save the history log as a CSV file")
        export_btn.clicked.connect(self._on_export_csv)
        bottom_row.addWidget(export_btn)

        bottom_row.addStretch()
        content.addLayout(bottom_row)

        # Initial load
        self._refresh_history()

    # ------------------------------------------------------------------
    # Active downloads
    # ------------------------------------------------------------------

    def _refresh_active(self):
        active = ActiveDownloads.all()
        # Clear the active layout
        while self._active_layout.count():
            item = self._active_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not active:
            self._active_placeholder = QLabel("No downloads in progress.")
            self._active_placeholder.setStyleSheet("color: #50507a; font-size: 12px;")
            self._active_layout.addWidget(self._active_placeholder)
        else:
            for entry in active:
                row = _ActiveDownloadRow(entry["name"])
                row.set_progress(entry["received"], entry["total"])
                self._active_layout.addWidget(row)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    _STATUS_MAP = {
        "All": None,
        "✅ Success": "success",
        "❌ Failed": "failed",
        "⏭ Skipped": "skipped",
    }

    _TYPE_MAP = {
        "All": None,
        "🎨 Texture Pack": "texture_pack",
        "🔧 PNACH Patch": "pnach",
        "🖼 Cover Art": "cover_art",
        "💾 Game Save": "save",
        "🕹 Cheat": "cheat",
        "📦 Other": "other",
    }

    def _refresh_history(self):
        status_filter = self._STATUS_MAP.get(self._status_combo.currentText())
        type_filter = self._TYPE_MAP.get(self._type_combo.currentText())
        serial_text = self._serial_edit.text().strip()
        serial_filter = serial_text if serial_text else None

        try:
            from src.core.download_history import list_history
            self._history_entries = list_history(
                self.config,
                status=status_filter,
                mod_type=type_filter,
                serial=serial_filter,
            )
        except Exception as exc:
            self._history_entries = []
            self._detail_label.setText(f"<i>Could not read history: {exc}</i>")

        self._list_widget.clear()
        for entry in self._history_entries:
            label = (
                f"{entry.timestamp[:10]}  {entry.status_label}  "
                f"{entry.type_label}  {entry.mod_name}"
            )
            self._list_widget.addItem(label)

        if not self._history_entries:
            self._detail_label.setText("<i>No entries found.</i>")

        self._delete_btn.setEnabled(False)

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._history_entries):
            self._detail_label.setText("← Select an entry to see details")
            self._delete_btn.setEnabled(False)
            return

        e = self._history_entries[row]

        try:
            from src.core.download_history import STATUS_COLOR
            color = STATUS_COLOR.get(e.status, "#555")
        except Exception:
            color = "#555"

        html = (
            f"<b>{e.mod_name}</b><br><br>"
            f"<b>Type:</b> {e.type_label}<br>"
            f"<b>Status:</b> <span style='color:{color}'>{e.status_label}</span><br>"
            f"<b>Timestamp:</b> {e.timestamp}<br>"
        )
        if e.serial:
            html += f"<b>Serial:</b> {e.serial}<br>"
        if e.source_url:
            html += f"<b>Source:</b> <code>{e.source_url}</code><br>"
        if e.size_bytes > 0:
            html += f"<b>Size:</b> {e.size_label}<br>"
        if e.note:
            html += f"<b>Note:</b> {e.note}<br>"
        html += f"<br><small><i>ID: {e.id}</i></small>"

        self._detail_label.setText(html)
        self._delete_btn.setEnabled(True)

    def _on_delete_entry(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._history_entries):
            return
        entry = self._history_entries[row]
        reply = QMessageBox.question(
            self,
            "Delete Entry",
            f"Remove this entry from the history log?\n\n{entry.mod_name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from src.core.download_history import delete_entry
        delete_entry(entry, self.config)
        self._refresh_history()

    def _on_clear(self):
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Delete ALL entries from the history log?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from src.core.download_history import clear_history
        count = clear_history(self.config)
        self._refresh_history()
        QMessageBox.information(
            self,
            "✅ History Cleared",
            f"Removed {count} entr{'y' if count == 1 else 'ies'} from the history log.",
        )

    def _on_export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export History CSV",
            "download_history.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            from src.core.download_history import export_history_csv
            result = export_history_csv(self.config, path=path)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        QMessageBox.information(
            self,
            "✅ Export Complete",
            f"History exported to:\n{result}",
        )

    def refresh(self):
        """Called when the user navigates to this panel."""
        self._refresh_active()
        self._refresh_history()
