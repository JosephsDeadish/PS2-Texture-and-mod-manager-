"""Downloads panel — active downloads and history.

Shows currently in-progress downloads with progress indicators, and an
inline download-history log that was previously only accessible as a
pop-up dialog from the Browse panel.
"""

from __future__ import annotations

import html
import logging
import threading as _threading
import webbrowser
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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

from src.core.config_manager import save_config, ui_state_bucket
from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel
from src.ui.url_helpers import open_external_url

logger = logging.getLogger(__name__)


def _history_summary_message(
    entry_count: int, filters_active: bool, total: int | None = None,
) -> str:
    """Return a compact history summary for the current filter state."""
    if entry_count <= 0:
        if filters_active:
            return "No history entries match the current filters. Clear filters to see more."
        return "No download history entries recorded yet. Finished downloads will appear here."

    noun = "entry" if entry_count == 1 else "entries"
    if total is not None and filters_active:
        return f"Showing {entry_count} of {total} download history entries."
    if filters_active:
        return f"Showing {entry_count} matching download history {noun}."
    return f"Showing {entry_count} download history {noun}."


_HISTORY_SORTS = ("Newest first", "Oldest first", "Name (A–Z)", "Largest first")


def _filter_history(entries, status, mod_type, serial, query, sort):
    serial = "".join(c for c in serial.casefold() if c.isalnum())
    terms = query.casefold().split()
    matches = []
    for entry in entries:
        if status and entry.status != status:
            continue
        entry_type = "save" if entry.mod_type == "save_file" else entry.mod_type
        if mod_type and entry_type != mod_type:
            continue
        normalized_serial = "".join(c for c in str(entry.serial or "").casefold() if c.isalnum())
        if serial and serial not in normalized_serial:
            continue
        searchable = " ".join(str(value or "") for value in (
            entry.mod_name, entry.serial, entry.source_url, entry.note,
            entry.type_label, entry.status_label,
        )).casefold()
        if all(term in searchable for term in terms):
            matches.append(entry)
    # The history log is already newest-first; retain that order for ties.
    if sort == "Oldest first":
        matches.reverse()
    elif sort == "Name (A–Z)":
        matches.sort(key=lambda entry: entry.mod_name.casefold())
    elif sort == "Largest first":
        matches.sort(key=lambda entry: entry.size_bytes, reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Single active-download row widget
# ---------------------------------------------------------------------------

def _download_size(value: int) -> str:
    size = max(0, value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _download_source_url(value: str) -> str:
    """Only offer browser actions for a complete HTTP(S) source URL."""
    try:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            return url
    except (AttributeError, ValueError):
        pass
    return ""


class _ActiveDownloadRow(QWidget):
    """Stable row for one transfer, including its post-download installation."""

    status_message = pyqtSignal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QProgressBar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        header = QHBoxLayout()
        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet("color: #c0c0e0;")
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._name_lbl.setWordWrap(True)
        header.addWidget(self._name_lbl, 1)
        self._open_source_btn = QPushButton("Open Source")
        self._open_source_btn.clicked.connect(self._open_source)
        header.addWidget(self._open_source_btn)
        self._copy_source_btn = QPushButton("Copy URL")
        self._copy_source_btn.clicked.connect(self._copy_source)
        header.addWidget(self._copy_source_btn)
        layout.addLayout(header)
        self._status_lbl = QLabel()
        self._status_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate by default
        self._bar.setFixedHeight(14)
        layout.addWidget(self._bar)
        self._source_url = ""
        self.update_entry({"name": name, "received": 0, "total": 0})

    def update_entry(self, entry):
        name = entry["name"]
        self._name_lbl.setText(name)
        self._name_lbl.setToolTip(name)
        self.setAccessibleName(f"Active download: {name}")
        self._source_url = _download_source_url(entry.get("source_url", ""))
        for button in (self._open_source_btn, self._copy_source_btn):
            button.setEnabled(bool(self._source_url))
            button.setToolTip(self._source_url or "No HTTP(S) source URL available")
        received, total = entry["received"], entry["total"]
        if entry.get("phase") == "installing":
            self._bar.setRange(0, 0)
            text = f"Installing • transfer finished • {_download_size(received)} received"
        else:
            self.set_progress(received, total)
            if total > 0:
                percent = min(100, max(0, received) * 100 // total)
                text = f"Downloading • {percent}% • {_download_size(received)} / {_download_size(total)}"
            elif received > 0:
                text = f"Downloading • {_download_size(received)} received • total unknown"
            else:
                text = "Connecting • waiting for file data"
        self._status_lbl.setText(text)
        self._bar.setAccessibleName(text)

    def set_progress(self, received: int, total: int):
        if total > 0:
            # Qt progress values are signed 32-bit integers, unlike byte counts.
            self._bar.setRange(0, 1000)
            self._bar.setValue(min(1000, max(0, received) * 1000 // total))
        else:
            self._bar.setRange(0, 0)

    def set_done(self):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)

    def _open_source(self):
        if self._source_url and open_external_url(
            self._source_url, parent=self, context="active download source",
        ):
            self.status_message.emit("Opened the active download source in your browser.")

    def _copy_source(self):
        if not self._source_url:
            return
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("clipboard unavailable")
            clipboard.setText(self._source_url)
        except Exception as exc:
            logger.warning("Could not copy active download source: %s", exc)
            self.status_message.emit("Could not copy the active download source URL.")
            return
        self.status_message.emit("Copied the active download source URL.")


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
    def register(cls, download_id: str, name: str, *, source_url: str = "") -> None:
        with cls._lock:
            cls._entries[download_id] = {
                "id": download_id, "name": name, "received": 0, "total": 0,
                "source_url": source_url, "phase": "downloading",
            }

    @classmethod
    def update(cls, download_id: str, received: int, total: int) -> None:
        with cls._lock:
            if download_id in cls._entries:
                cls._entries[download_id]["received"] = received
                cls._entries[download_id]["total"] = total

    @classmethod
    def set_installing(cls, download_id: str) -> None:
        with cls._lock:
            if download_id in cls._entries:
                cls._entries[download_id]["phase"] = "installing"

    @classmethod
    def finish(cls, download_id: str) -> None:
        with cls._lock:
            cls._entries.pop(download_id, None)

    @classmethod
    def all(cls) -> list[dict]:
        with cls._lock:
            return [dict(entry) for entry in cls._entries.values()]

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
        self._all_history_entries: list = []
        self._history_stamp = None
        self._selected_source_url: str = ""
        self._active_rows: dict[str, _ActiveDownloadRow] = {}
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._on_history_filter_changed)
        self._build()
        # Poll active downloads when the panel is visible
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_downloads)

    def _last_paths_bucket(self) -> dict:
        return ui_state_bucket(self.config, "last_paths")

    def _history_panel_bucket(self) -> dict:
        return ui_state_bucket(self.config, "downloads_panel")

    def _save_panel_config(self, context: str) -> None:
        try:
            save_config(self.config)
        except Exception as exc:
            logger.warning("Could not save downloads panel config after %s: %s", context, exc)
            self._notify_status("Could not save downloads panel settings right now.")

    def _validated_splitter_sizes(self, sizes, *, action: str):
        if not isinstance(sizes, (list, tuple)):
            logger.warning(
                "Ignoring invalid download history splitter state while %s: expected a list, got %r",
                action,
                sizes,
            )
            return None
        try:
            cleaned = [int(size) for size in sizes]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Ignoring invalid download history splitter state while %s: %s",
                action,
                exc,
            )
            return None
        if len(cleaned) < 2:
            logger.warning(
                "Ignoring invalid download history splitter state while %s: expected at least 2 sizes, got %r",
                action,
                cleaned,
            )
            return None
        return cleaned

    def _notify_status(self, message: str) -> None:
        emitter = getattr(getattr(self, "status_message", None), "emit", None)
        if callable(emitter):
            emitter(message)
        else:
            logger.info(message)

    def _set_history_summary(self, message: str) -> None:
        summary_lbl = getattr(self, "_history_summary_lbl", None)
        setter = getattr(summary_lbl, "setText", None)
        if callable(setter):
            setter(message)

    def _save_history_splitter(self, *_args) -> None:
        splitter = getattr(self, "_history_splitter", None)
        if splitter is None:
            return
        sizes = self._validated_splitter_sizes(
            getattr(splitter, "sizes", lambda: [])(),
            action="saving",
        )
        if sizes is None:
            return
        self._history_panel_bucket()["history_splitter_sizes"] = sizes
        self._save_panel_config("updating download history splitter")

    def _restore_history_splitter(self) -> None:
        splitter = getattr(self, "_history_splitter", None)
        if splitter is None:
            return
        sizes = self._validated_splitter_sizes(
            self._history_panel_bucket().get("history_splitter_sizes", []),
            action="restoring",
        )
        if sizes is None:
            return
        if hasattr(splitter, "setSizes"):
            splitter.setSizes(sizes)

    def _save_history_selection(self, row: int) -> None:
        if getattr(self, "_history_state_syncing", False):
            return
        if row < 0 or row >= len(self._history_entries):
            return
        config = getattr(self, "config", None)
        if config is None:
            return
        entry = self._history_entries[row]
        entry_id = getattr(entry, "id", "")
        if not entry_id:
            return
        bucket = ui_state_bucket(config, "downloads_panel")
        if bucket.get("history_selected_entry_id") == entry_id:
            return
        bucket["history_selected_entry_id"] = str(entry_id)
        self._save_panel_config("updating download history selection")

    def _restore_history_selection(self) -> None:
        config = getattr(self, "config", None)
        if config is None:
            return
        entry_id = ui_state_bucket(config, "downloads_panel").get("history_selected_entry_id", "")
        if not isinstance(entry_id, str):
            logger.warning(
                "Saved download history entry %r is invalid; clearing selection",
                entry_id,
            )
            self._clear_history_selection_state(
                "clearing invalid download history selection",
            )
            return
        if not entry_id:
            return
        for row, entry in enumerate(self._history_entries):
            if getattr(entry, "id", "") != entry_id:
                continue
            self._history_state_syncing = True
            try:
                setter = getattr(self._list_widget, "setCurrentRow", None)
                if callable(setter):
                    setter(row)
                else:
                    self._on_selection_changed(row)
            finally:
                self._history_state_syncing = False
            return
        if any(entry.id == entry_id for entry in self._all_history_entries):
            return  # A filter temporarily hides the saved selection.
        logger.warning(
            "Saved download history entry %r is no longer available; clearing selection",
            entry_id,
        )
        self._clear_history_selection_state(
            "clearing missing download history selection",
        )

    def _clear_history_selection_state(self, context: str) -> None:
        config = getattr(self, "config", None)
        if config is None:
            return
        bucket = ui_state_bucket(config, "downloads_panel")
        if "history_selected_entry_id" not in bucket:
            return
        bucket.pop("history_selected_entry_id", None)
        self._save_panel_config(context)

    def _clear_history_filters(self) -> None:
        widgets = (self._status_combo, self._type_combo, self._serial_edit, self._search_edit)
        self._filter_timer.stop()
        for widget in widgets:
            setter = getattr(widget, "blockSignals", None)
            if callable(setter):
                setter(True)
        try:
            status_idx = self._status_combo.findText("All")
            if status_idx >= 0:
                self._status_combo.setCurrentIndex(status_idx)
            type_idx = self._type_combo.findText("All")
            if type_idx >= 0:
                self._type_combo.setCurrentIndex(type_idx)
            self._serial_edit.setText("")
            self._search_edit.setText("")
        finally:
            for widget in widgets:
                setter = getattr(widget, "blockSignals", None)
                if callable(setter):
                    setter(False)
        self._save_history_filters()
        self._apply_history_filters()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_active()
        self._poll_timer.start()

    def hideEvent(self, event):
        if self._filter_timer.isActive():
            self._on_history_filter_changed()
        super().hideEvent(event)
        self._poll_timer.stop()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        content = self._content_layout

        # ── Active downloads section ──────────────────────────────────────
        self._active_summary = QLabel("⬇  Active Downloads")
        self._active_summary.setStyleSheet("font-weight: bold; font-size: 13px; color: #a0a0d0;")
        self._active_summary.setWordWrap(True)
        content.addWidget(self._active_summary)

        self._active_container = QWidget()
        self._active_layout = QVBoxLayout(self._active_container)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(2)

        self._active_placeholder = QLabel(
            "No downloads in progress.\n"
            "Start a download from Browse to see transfer and installation progress here."
        )
        self._active_placeholder.setStyleSheet("color: #50507a; font-size: 12px;")
        self._active_placeholder.setWordWrap(True)
        self._active_layout.addWidget(self._active_placeholder)

        self._active_scroll = QScrollArea()
        self._active_scroll.setWidgetResizable(True)
        self._active_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._active_scroll.setMaximumHeight(240)
        self._active_scroll.setWidget(self._active_container)
        content.addWidget(self._active_scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1a1a3a;")
        content.addWidget(sep)

        # ── History section ───────────────────────────────────────────────
        hist_hdr = QLabel("📋  Download History")
        hist_hdr.setStyleSheet("font-weight: bold; font-size: 13px; color: #a0a0d0;")
        content.addWidget(hist_hdr)

        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search names, sources, notes…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setAccessibleName("Search download history")
        self._search_edit.textChanged.connect(self._on_history_text_changed)
        search_row.addWidget(self._search_edit, 1)
        search_row.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(_HISTORY_SORTS)
        self._sort_combo.currentIndexChanged.connect(self._on_history_filter_changed)
        search_row.addWidget(self._sort_combo)
        content.addLayout(search_row)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Status:"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["All", "✅ Success", "❌ Failed", "⏭ Skipped"])
        self._status_combo.currentIndexChanged.connect(self._on_history_filter_changed)
        filter_row.addWidget(self._status_combo)

        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "All", "🎨 Texture Pack", "🔧 PNACH Patch",
            "🖼 Cover Art", "💾 Game Save", "🕹 Cheat", "📦 Other",
        ])
        self._type_combo.currentIndexChanged.connect(self._on_history_filter_changed)
        filter_row.addWidget(self._type_combo)

        filter_row.addWidget(QLabel("Serial:"))
        self._serial_edit = QLineEdit()
        self._serial_edit.setPlaceholderText("Serial or fragment")
        self._serial_edit.setMaximumWidth(130)
        self._serial_edit.setToolTip("Match part of a serial, ignoring case and punctuation")
        self._serial_edit.textChanged.connect(self._on_history_text_changed)
        filter_row.addWidget(self._serial_edit)

        filter_row.addStretch()
        content.addLayout(filter_row)

        self._history_summary_lbl = QLabel("")
        self._history_summary_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._history_summary_lbl.setStyleSheet("color: #5060a0; font-size: 11px;")
        self._history_summary_lbl.setWordWrap(True)
        content.addWidget(self._history_summary_lbl)

        self._empty_filters_btn = QPushButton("Clear Filters")
        self._empty_filters_btn.clicked.connect(self._clear_history_filters)
        self._empty_filters_btn.hide()
        content.addWidget(self._empty_filters_btn)

        # Splitter: list (left) | detail (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self._list_widget = QListWidget()
        self._list_widget.setWordWrap(True)
        self._list_widget.setSpacing(3)
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
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setWidget(self._detail_label)
        rl.addWidget(detail_scroll, 1)

        right_sep = QFrame()
        right_sep.setFrameShape(QFrame.Shape.HLine)
        rl.addWidget(right_sep)

        btn_row = QHBoxLayout()
        self._delete_btn = QPushButton("🗑  Delete Entry")
        self._delete_btn.setToolTip("Remove this entry from the history log")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_entry)
        rl.addWidget(self._delete_btn)

        self._open_source_btn = QPushButton("🌐 Open Source")
        self._open_source_btn.setToolTip("Open the selected entry's source page in your browser")
        self._open_source_btn.setEnabled(False)
        self._open_source_btn.clicked.connect(self._open_selected_source)
        btn_row.addWidget(self._open_source_btn)

        self._copy_source_btn = QPushButton("📋 Copy Source URL")
        self._copy_source_btn.setToolTip("Copy the selected entry's source URL to the clipboard")
        self._copy_source_btn.setEnabled(False)
        self._copy_source_btn.clicked.connect(self._copy_selected_source)
        btn_row.addWidget(self._copy_source_btn)

        btn_row.addStretch()
        rl.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self._history_splitter = splitter
        splitter_moved = getattr(splitter, "splitterMoved", None)
        if callable(getattr(splitter_moved, "connect", None)):
            splitter_moved.connect(self._save_history_splitter)
        content.addWidget(splitter, 1)

        # Bottom actions
        bottom_row = QHBoxLayout()
        refresh_hist_btn = QPushButton("🔄 Refresh")
        refresh_hist_btn.setToolTip("Reload the history log from disk")
        refresh_hist_btn.clicked.connect(self._refresh_history)
        bottom_row.addWidget(refresh_hist_btn)

        clear_hist_btn = QPushButton("✖ Clear Filters")
        clear_hist_btn.setToolTip("Reset history search, status, type, and serial filters")
        clear_hist_btn.clicked.connect(self._clear_history_filters)
        bottom_row.addWidget(clear_hist_btn)

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

        self._restore_history_view()
        self._restore_history_filters()
        self._restore_history_splitter()

        # Initial load
        self._refresh_history()

    # ------------------------------------------------------------------
    # History filter state
    # ------------------------------------------------------------------

    def _history_filter_state(self) -> tuple[str, str, str]:
        return (
            self._status_combo.currentText(),
            self._type_combo.currentText(),
            self._serial_edit.text().strip(),
        )

    def _save_history_filters(self) -> None:
        status, mod_type, serial = self._history_filter_state()
        self.config.download_history_status_filter = status or "All"
        self.config.download_history_type_filter = mod_type or "All"
        self.config.download_history_serial_filter = serial
        self._history_panel_bucket().update({
            "query": self._search_edit.text().strip(),
            "sort": self._sort_combo.currentText(),
        })
        self._save_panel_config("updating download history filters")

    def _restore_history_view(self) -> None:
        bucket = self._history_panel_bucket()
        query = bucket.get("query", "")
        sort = bucket.get("sort", _HISTORY_SORTS[0])
        for widget in (self._search_edit, self._sort_combo):
            widget.blockSignals(True)
        try:
            self._search_edit.setText(query if isinstance(query, str) else "")
            self._sort_combo.setCurrentIndex(
                _HISTORY_SORTS.index(sort) if sort in _HISTORY_SORTS else 0
            )
        finally:
            for widget in (self._search_edit, self._sort_combo):
                widget.blockSignals(False)

    def _update_history_source_actions(self) -> None:
        enabled = bool(self._selected_source_url.strip())
        for attr in ("_open_source_btn", "_copy_source_btn"):
            button = getattr(self, attr, None)
            setter = getattr(button, "setEnabled", None)
            if callable(setter):
                setter(enabled)

    def _restore_history_filters(self) -> None:
        state_changed = False
        status = getattr(self.config, "download_history_status_filter", "All") or "All"
        mod_type = getattr(self.config, "download_history_type_filter", "All") or "All"
        serial = getattr(self.config, "download_history_serial_filter", "") or ""
        if not isinstance(status, str):
            logger.warning(
                "Saved download history status filter %r is invalid; using All",
                status,
            )
            status = str(status)
            state_changed = True
        if not isinstance(mod_type, str):
            logger.warning(
                "Saved download history type filter %r is invalid; using All",
                mod_type,
            )
            mod_type = str(mod_type)
            state_changed = True
        if not isinstance(serial, str):
            logger.warning(
                "Saved download history serial filter %r is invalid; using text form",
                serial,
            )
            serial = str(serial)
            state_changed = True

        for widget in (self._status_combo, self._type_combo, self._serial_edit):
            widget.blockSignals(True)

        all_status_idx = self._status_combo.findText("All")
        idx = self._status_combo.findText(status)
        if idx >= 0:
            self._status_combo.setCurrentIndex(idx)
        elif status != "All":
            logger.warning(
                "Saved download history status filter %r is no longer available; using All",
                status,
            )
            if all_status_idx >= 0:
                self._status_combo.setCurrentIndex(all_status_idx)
            state_changed = True
        all_type_idx = self._type_combo.findText("All")
        idx = self._type_combo.findText(mod_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        elif mod_type != "All":
            logger.warning(
                "Saved download history type filter %r is no longer available; using All",
                mod_type,
            )
            if all_type_idx >= 0:
                self._type_combo.setCurrentIndex(all_type_idx)
            state_changed = True
        self._serial_edit.setText(serial)

        for widget in (self._status_combo, self._type_combo, self._serial_edit):
            widget.blockSignals(False)

        if state_changed:
            self._save_history_filters()

    def _on_history_filter_changed(self, *_args):
        self._filter_timer.stop()
        self._save_history_filters()
        self._apply_history_filters()

    def _on_history_text_changed(self, *_args):
        self._filter_timer.start()

    # ------------------------------------------------------------------
    # Active downloads
    # ------------------------------------------------------------------

    def _refresh_active(self):
        active = ActiveDownloads.all()
        active_ids = {entry["id"] for entry in active}
        for download_id in list(self._active_rows):
            if download_id not in active_ids:
                row = self._active_rows.pop(download_id)
                self._active_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
        for entry in active:
            row = self._active_rows.get(entry["id"])
            if row is None:
                row = _ActiveDownloadRow(entry["name"])
                row.status_message.connect(self._notify_status)
                self._active_rows[entry["id"]] = row
                self._active_layout.addWidget(row)
            row.update_entry(entry)
        self._active_placeholder.setVisible(not active)
        installing = sum(entry["phase"] == "installing" for entry in active)
        self._active_summary.setText(
            f"⬇  Active Downloads: {len(active)}"
            f" • {len(active) - installing} downloading • {installing} installing"
            if active else "⬇  Active Downloads: none"
        )

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

    def _history_file_stamp(self):
        from src.core.download_history import get_history_file
        try:
            stat = get_history_file(self.config).stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("Could not inspect download history: %s", exc)
            return None

    def _poll_downloads(self):
        self._refresh_active()
        if self._history_file_stamp() != self._history_stamp:
            self._refresh_history()

    def _refresh_history(self):
        if self._filter_timer.isActive():
            self._filter_timer.stop()
            self._save_history_filters()
        self._history_stamp = self._history_file_stamp()
        try:
            from src.core.download_history import list_history
            self._all_history_entries = list_history(self.config)
        except Exception as exc:
            logger.warning("Failed to load download history: %s", exc)
            self._all_history_entries = []
            self._apply_history_filters()
            empty_msg = f"Could not read history: {exc}"
            self._list_widget.clear()
            self._list_widget.addItem(empty_msg)
            self._detail_label.setText(f"<i>{html.escape(empty_msg)}</i>")
            self._set_history_summary("Could not read download history.")
            return
        self._apply_history_filters()

    def _apply_history_filters(self):
        status_filter = self._STATUS_MAP.get(self._status_combo.currentText())
        type_filter = self._TYPE_MAP.get(self._type_combo.currentText())
        serial_text = self._serial_edit.text().strip()
        serial_filter = serial_text if serial_text else None
        query = self._search_edit.text().strip()
        filters_active = bool(status_filter or type_filter or serial_filter or query)
        self._list_widget.clear()
        self._history_entries = []
        self._detail_label.setText("← Select an entry to see details")
        self._selected_source_url = ""
        self._update_history_source_actions()
        self._delete_btn.setEnabled(False)

        self._history_entries = _filter_history(
            self._all_history_entries, status_filter, type_filter,
            serial_text, query, self._sort_combo.currentText(),
        )
        self._empty_filters_btn.setVisible(not self._history_entries and filters_active)

        for entry in self._history_entries:
            label = (
                f"{entry.status_label}  {entry.mod_name}\n"
                f"{entry.timestamp[:16].replace('T', ' ')}  ·  {entry.type_label}"
                + (f"  ·  {entry.serial}" if entry.serial else "")
            )
            self._list_widget.addItem(label)

        if not self._history_entries:
            if not filters_active:
                empty_msg = "No download history entries recorded yet."
            else:
                empty_msg = "No history entries match the current filters."
            self._list_widget.addItem(empty_msg)
            self._detail_label.setText(f"<i>{empty_msg}</i>")
            self._selected_source_url = ""
            self._update_history_source_actions()
            self._set_history_summary(_history_summary_message(0, filters_active))
        else:
            self._set_history_summary(
                _history_summary_message(
                    len(self._history_entries), filters_active, len(self._all_history_entries),
                )
            )
            self._restore_history_selection()

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._history_entries):
            self._detail_label.setText("← Select an entry to see details")
            self._delete_btn.setEnabled(False)
            self._selected_source_url = ""
            self._update_history_source_actions()
            return

        e = self._history_entries[row]
        self._selected_source_url = str(getattr(e, "source_url", "") or "").strip()
        self._update_history_source_actions()

        try:
            from src.core.download_history import STATUS_COLOR
            color = STATUS_COLOR.get(e.status, "#555")
        except Exception as exc:
            logger.warning("Failed to resolve download history status color: %s", exc)
            color = "#555"

        mod_name = html.escape(str(e.mod_name))
        type_label = html.escape(str(e.type_label))
        status_label = html.escape(str(e.status_label))
        timestamp = html.escape(str(e.timestamp))
        serial = html.escape(str(e.serial))
        source_url = html.escape(str(getattr(e, "source_url", "")))
        size_label = html.escape(str(e.size_label))
        note = html.escape(str(e.note))
        entry_id = html.escape(str(e.id))

        details_html = (
            f"<b>{mod_name}</b><br><br>"
            f"<b>Type:</b> {type_label}<br>"
            f"<b>Status:</b> <span style='color:{color}'>{status_label}</span><br>"
            f"<b>Timestamp:</b> {timestamp}<br>"
        )
        if e.serial:
            details_html += f"<b>Serial:</b> {serial}<br>"
        if getattr(e, "source_url", ""):
            details_html += f"<b>Source:</b> <code>{source_url}</code><br>"
        if e.size_bytes > 0:
            details_html += f"<b>Size:</b> {size_label}<br>"
        if e.note:
            details_html += f"<b>Note:</b> {note}<br>"
        details_html += f"<br><small><i>ID: {entry_id}</i></small>"

        self._detail_label.setText(details_html)
        self._delete_btn.setEnabled(True)
        self._save_history_selection(row)

    def _open_selected_source(self) -> None:
        url = self._selected_source_url.strip()
        if not url:
            self._notify_status("No source URL is available for this history entry.")
            return
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            logger.warning("Failed to open download history source URL %s: %s", url, exc)
            self._notify_status("Could not open the selected source URL.")
            return
        if not opened:
            logger.warning("Failed to open download history source URL %s: browser refused", url)
            self._notify_status("Could not open the selected source URL.")
            return
        self._notify_status("Opened the selected source URL in your browser.")

    def _copy_selected_source(self) -> None:
        url = self._selected_source_url.strip()
        if not url:
            self._notify_status("No source URL is available to copy.")
            return
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("clipboard unavailable")
            clipboard.setText(url)
        except Exception as exc:
            logger.warning("Failed to copy download history source URL %s: %s", url, exc)
            self._notify_status("Could not copy the selected source URL.")
            return
        self._notify_status("Copied the selected source URL to the clipboard.")

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
        try:
            delete_entry(entry, self.config)
        except Exception as exc:
            logger.warning("Failed to delete download history entry: %s", exc)
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return
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
        try:
            count = clear_history(self.config)
        except Exception as exc:
            logger.warning("Failed to clear download history: %s", exc)
            QMessageBox.critical(self, "Clear Failed", str(exc))
            return
        self._refresh_history()
        QMessageBox.information(
            self,
            "✅ History Cleared",
            f"Removed {count} entr{'y' if count == 1 else 'ies'} from the history log.",
        )

    def _on_export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        last_paths = self._last_paths_bucket()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export History CSV",
            last_paths.get("download_history_export_dir", "download_history.csv"),
            "CSV files (*.csv)",
        )
        if not path:
            return
        self._last_paths_bucket()["download_history_export_dir"] = str(Path(path).parent)
        self._save_panel_config("updating history export folder")
        try:
            from src.core.download_history import export_history_csv
            result = export_history_csv(self.config, path=path)
        except Exception as exc:
            logger.warning("Failed to export download history CSV: %s", exc)
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
