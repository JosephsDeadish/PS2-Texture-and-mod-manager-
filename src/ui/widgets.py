"""Reusable UI widgets for PS2 Mod Manager."""

import os
import textwrap
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap, QFont, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QProgressBar,
    QFileDialog,
    QLineEdit,
    QDialog,
    QDialogButtonBox,
    QScrollArea,
    QApplication,
    QGridLayout,
    QTextEdit,
    QMessageBox,
)

from src.models.mod import ModInfo, ModType, ConflictInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_label(text: str, object_name: str = "", bold: bool = False) -> QLabel:
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    if bold:
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
    return lbl


def _icon_for_type(mod_type: ModType) -> str:
    """Return an emoji-style icon string for a mod type."""
    return {
        ModType.TEXTURE_PACK: "🎨",
        ModType.PNACH: "🔧",
        ModType.COVER_ART: "🖼️",
        ModType.SAVE_FILE: "💾",
        ModType.CHEAT: "⚡",
    }.get(mod_type, "📦")


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / (1024 ** 3):.2f} GB"


# ---------------------------------------------------------------------------
# Mod Item Widget
# ---------------------------------------------------------------------------

class ModItemWidget(QFrame):
    """A single row in the mod list showing mod info + toggle + action buttons."""

    toggled = pyqtSignal(str, bool)        # (mod_id, enabled)
    remove_requested = pyqtSignal(str)     # mod_id
    priority_up = pyqtSignal(str)          # mod_id
    priority_down = pyqtSignal(str)        # mod_id
    details_requested = pyqtSignal(str)    # mod_id
    edit_requested = pyqtSignal(str)       # mod_id

    def __init__(self, mod: ModInfo, has_conflict: bool = False, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.has_conflict = has_conflict
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("mod_item_conflict" if self.has_conflict else "mod_item")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(10)

        # Type icon
        icon_lbl = QLabel(_icon_for_type(self.mod.mod_type))
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 20px;")
        outer.addWidget(icon_lbl)

        # Thumbnail
        thumb = QLabel()
        thumb.setFixedSize(48, 48)
        thumb.setStyleSheet("background: #0f1830; border-radius: 4px;")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.mod.thumbnail_path and Path(self.mod.thumbnail_path).exists():
            pix = QPixmap(self.mod.thumbnail_path).scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            thumb.setPixmap(pix)
        else:
            thumb.setText("🎮")
            thumb.setStyleSheet("font-size: 22px; background: #0f1830; border-radius: 4px;")
        outer.addWidget(thumb)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(2)
        name_row = QHBoxLayout()
        name_lbl = QLabel(self.mod.name)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff;")
        name_row.addWidget(name_lbl)

        if self.has_conflict:
            warn = QLabel("⚠ Conflict")
            warn.setObjectName("badge")
            warn.setStyleSheet(
                "background:#7a2020; color:#ff8080; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            name_row.addWidget(warn)

        if self.mod.has_update:
            upd = QLabel("↑ Update")
            upd.setStyleSheet(
                "background:#1a4a6a; color:#80c8ff; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            name_row.addWidget(upd)

        name_row.addStretch()
        info.addLayout(name_row)

        meta_parts = []
        if self.mod.author:
            meta_parts.append(f"by {self.mod.author}")
        if self.mod.version:
            meta_parts.append(f"v{self.mod.version}")
        if self.mod.game_id:
            meta_parts.append(f"Game: {self.mod.game_id}")
        if self.mod.size_bytes:
            meta_parts.append(_fmt_size(self.mod.size_bytes))

        meta_lbl = QLabel("  •  ".join(meta_parts))
        meta_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
        info.addWidget(meta_lbl)

        if self.mod.description:
            desc = QLabel(textwrap.shorten(self.mod.description, width=100, placeholder="…"))
            desc.setStyleSheet("color: #9090b0; font-size: 11px;")
            desc.setWordWrap(True)
            info.addWidget(desc)

        outer.addLayout(info, 1)

        # Priority controls
        prio_col = QVBoxLayout()
        prio_col.setSpacing(2)
        up_btn = QPushButton("▲")
        up_btn.setFixedSize(24, 24)
        up_btn.setToolTip("Higher priority (wins conflicts)")
        up_btn.clicked.connect(lambda: self.priority_up.emit(self.mod.id))
        dn_btn = QPushButton("▼")
        dn_btn.setFixedSize(24, 24)
        dn_btn.setToolTip("Lower priority")
        dn_btn.clicked.connect(lambda: self.priority_down.emit(self.mod.id))
        prio_lbl = QLabel(f"#{self.mod.priority}")
        prio_lbl.setStyleSheet("color: #7070a0; font-size: 10px;")
        prio_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prio_col.addWidget(up_btn)
        prio_col.addWidget(prio_lbl)
        prio_col.addWidget(dn_btn)
        outer.addLayout(prio_col)

        # Action buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        info_btn = QPushButton("ℹ")
        info_btn.setFixedSize(28, 28)
        info_btn.setToolTip("Details")
        info_btn.clicked.connect(lambda: self.details_requested.emit(self.mod.id))
        btn_col.addWidget(info_btn)

        edit_btn = QPushButton("✏")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setToolTip("Edit metadata")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.mod.id))
        btn_col.addWidget(edit_btn)

        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(28, 28)
        del_btn.setObjectName("danger_btn")
        del_btn.setToolTip("Remove mod")
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self.mod.id))
        btn_col.addWidget(del_btn)

        outer.addLayout(btn_col)

        # Toggle
        self.toggle = QCheckBox()
        self.toggle.setChecked(self.mod.enabled)
        self.toggle.setToolTip("Enable / Disable")
        self.toggle.toggled.connect(lambda v: self.toggled.emit(self.mod.id, v))
        outer.addWidget(self.toggle)


# ---------------------------------------------------------------------------
# Mod Details Dialog
# ---------------------------------------------------------------------------

class ModDetailsDialog(QDialog):
    """Full-screen details dialog for a mod."""

    def __init__(self, mod: ModInfo, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(f"Mod Details — {mod.name}")
        self.setMinimumSize(560, 420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QHBoxLayout()
        icon_lbl = QLabel(_icon_for_type(self.mod.mod_type))
        icon_lbl.setStyleSheet("font-size: 40px;")
        header.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.addWidget(_make_label(self.mod.name, bold=True))
        title_col.addWidget(_make_label(f"by {self.mod.author}  •  v{self.mod.version}"))
        if self.mod.game_id:
            title_col.addWidget(_make_label(f"Game ID: {self.mod.game_id}"))
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Description
        if self.mod.description:
            desc = QTextEdit()
            desc.setPlainText(self.mod.description)
            desc.setReadOnly(True)
            desc.setMaximumHeight(100)
            layout.addWidget(desc)

        # Files
        if self.mod.files:
            files_lbl = QLabel(f"Files ({len(self.mod.files)}):")
            files_lbl.setStyleSheet("font-weight: bold; color: #b0b0d0;")
            layout.addWidget(files_lbl)
            files_text = QTextEdit()
            files_text.setPlainText("\n".join(self.mod.files[:50]))
            files_text.setReadOnly(True)
            files_text.setMaximumHeight(120)
            layout.addWidget(files_text)

        # Source
        if self.mod.source_url:
            src_row = QHBoxLayout()
            src_row.addWidget(QLabel("Source:"))
            src_lbl = QLabel(
                f'<a href="{self.mod.source_url}" style="color:#6090d0;">'
                f"{self.mod.source_url[:60]}</a>"
            )
            src_lbl.setOpenExternalLinks(True)
            src_row.addWidget(src_lbl, 1)
            layout.addLayout(src_row)

        # Path
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Location:"))
        path_row.addWidget(QLabel(self.mod.path), 1)
        layout.addLayout(path_row)

        layout.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ---------------------------------------------------------------------------
# Conflict Resolution Dialog
# ---------------------------------------------------------------------------

class ConflictDialog(QDialog):
    """Shows conflicts and lets the user choose resolution."""

    def __init__(self, conflicts: list, db, parent=None):
        super().__init__(parent)
        self.conflicts = conflicts
        self.db = db
        self.setWindowTitle("Mod Conflicts Detected")
        self.setMinimumSize(640, 480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("⚠ The following mods have conflicting files")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff8080;")
        layout.addWidget(header)

        sub = QLabel(
            "For each conflict, choose which mod should win (higher priority overrides).\n"
            "You can also disable one of the conflicting mods."
        )
        sub.setStyleSheet("color: #9090b0;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(10)

        for conflict in self.conflicts:
            mod_a = self.db.get(conflict.mod_a_id)
            mod_b = self.db.get(conflict.mod_b_id)
            if not mod_a or not mod_b:
                continue

            frame = QFrame()
            frame.setObjectName("card")
            f_layout = QVBoxLayout(frame)

            title = QLabel(f"🔴  {mod_a.name}  ↔  {mod_b.name}")
            title.setStyleSheet("font-weight: bold; color: #ff8080;")
            f_layout.addWidget(title)

            files_txt = ", ".join(conflict.conflicting_files[:5])
            if len(conflict.conflicting_files) > 5:
                files_txt += f" (+{len(conflict.conflicting_files) - 5} more)"
            f_layout.addWidget(QLabel(f"Conflicting files: {files_txt}"))

            btn_row = QHBoxLayout()
            a_wins = QPushButton(f"✅ {mod_a.name} wins")
            a_wins.setObjectName("success_btn")
            b_wins = QPushButton(f"✅ {mod_b.name} wins")
            b_wins.setObjectName("success_btn")
            ignore_btn = QPushButton("⚡ Allow both (unexpected effects)")
            ignore_btn.setObjectName("primary_btn")

            def _make_resolver(ma, mb, which):
                def _resolve():
                    if which == "a":
                        ma.priority = max(ma.priority, mb.priority) + 1
                        self.db.update(ma)
                    elif which == "b":
                        mb.priority = max(ma.priority, mb.priority) + 1
                        self.db.update(mb)
                return _resolve

            a_wins.clicked.connect(_make_resolver(mod_a, mod_b, "a"))
            b_wins.clicked.connect(_make_resolver(mod_a, mod_b, "b"))

            btn_row.addWidget(a_wins)
            btn_row.addWidget(b_wins)
            btn_row.addWidget(ignore_btn)
            f_layout.addLayout(btn_row)
            c_layout.addWidget(frame)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        layout.addWidget(btns)


# ---------------------------------------------------------------------------
# Path chooser widget
# ---------------------------------------------------------------------------

class PathChooser(QWidget):
    """Label + line edit + browse button for folder selection."""

    path_changed = pyqtSignal(str)

    def __init__(self, label: str = "Path:", placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFixedWidth(130)
        layout.addWidget(lbl)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self.path_changed.emit)
        layout.addWidget(self.edit, 1)

        browse = QPushButton("Browse…")
        browse.setFixedWidth(90)
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", self.edit.text())
        if d:
            self.edit.setText(d)
            self.path_changed.emit(d)

    def get_path(self) -> str:
        return self.edit.text()

    def set_path(self, path: str):
        self.edit.setText(path)


# ---------------------------------------------------------------------------
# Empty state widget
# ---------------------------------------------------------------------------

class EmptyStateWidget(QWidget):
    """Shown when a list is empty."""

    def __init__(self, icon: str = "📦", message: str = "Nothing here yet", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 56px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("color: #5050a0; font-size: 16px;")
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl)


# ---------------------------------------------------------------------------
# Download progress widget
# ---------------------------------------------------------------------------

class DownloadProgressWidget(QWidget):
    """Shows download progress for a single item."""

    cancelled = pyqtSignal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.name_lbl = QLabel(name)
        self.name_lbl.setFixedWidth(200)
        layout.addWidget(self.name_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress, 1)

        self.status_lbl = QLabel("Waiting…")
        self.status_lbl.setFixedWidth(120)
        layout.addWidget(self.status_lbl)

        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedSize(28, 28)
        cancel_btn.setObjectName("danger_btn")
        cancel_btn.clicked.connect(self.cancelled.emit)
        layout.addWidget(cancel_btn)

    def update_progress(self, received: int, total: int):
        if total > 0:
            pct = int(received / total * 100)
            self.progress.setValue(pct)
            self.status_lbl.setText(f"{_fmt_size(received)} / {_fmt_size(total)}")
        else:
            self.progress.setRange(0, 0)
            self.status_lbl.setText(_fmt_size(received))

    def set_complete(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_lbl.setText("✅ Done")

    def set_error(self, msg: str):
        self.status_lbl.setText(f"❌ {msg[:30]}")
