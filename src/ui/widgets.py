"""Reusable UI widgets for PS2 Mod Manager."""

import os
import textwrap
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap, QFont, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTabWidget,
)

from src.models.mod import ModInfo, ModType, ConflictInfo

# ---------------------------------------------------------------------------
# PnachCodePickerDialog
# ---------------------------------------------------------------------------

class PnachCodePickerDialog(QDialog):
    """Let the user build a custom merged PNACH by choosing which mod wins
    each conflicting address, then merging any non-conflicting codes from all
    mods.

    After the dialog is accepted, call :meth:`write_merged` to produce the
    merged ``.pnach`` file.
    """

    def __init__(self, pnach_conflicts: list, db, parent=None):
        """
        *pnach_conflicts* — list of dicts from ``ModManager.detect_pnach_conflicts()``.
        *db* — ``ModDatabase`` instance.
        """
        super().__init__(parent)
        self.pnach_conflicts = pnach_conflicts
        self.db = db
        # Map (game_crc, processor, address) → chosen mod_id  (None = ask user)
        self._choices: dict = {}
        self.setWindowTitle("🔧 PNACH Code Picker — Build Custom Merged Patch")
        self.setMinimumSize(820, 580)
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        from collections import defaultdict
        from src.core.pnach_analyzer import describe_patch, group_conflicts_by_function

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        header = QLabel("🔧  Build Your Own Merged PNACH Patch")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #70b0ff;")
        layout.addWidget(header)

        intro = QLabel(
            "For each conflicting memory address, choose which mod's code you want to use.\n"
            "All non-conflicting codes from every selected mod are automatically included."
        )
        intro.setStyleSheet("color: #9090b0; font-size: 12px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(8)

        # Group by category using the analyzer
        grouped = group_conflicts_by_function(self.pnach_conflicts)
        category_order = ["physics", "gameplay", "graphics", "audio", "cheat",
                          "hardware_registers", "unknown"]
        category_labels = {
            "physics": "⚡ Physics & Movement",
            "gameplay": "🎮 Gameplay",
            "graphics": "🖥️ Graphics / Widescreen",
            "audio": "🔊 Audio",
            "cheat": "🌟 Cheats & Stats",
            "hardware_registers": "🔌 Hardware Registers",
            "unknown": "❓ Unknown / Other",
        }
        all_cats = list(grouped.keys())
        ordered = [c for c in category_order if c in all_cats]
        ordered += [c for c in all_cats if c not in ordered]

        self._radio_groups: dict = {}  # (crc, proc, addr) → {mod_id: QRadioButton}

        for cat in ordered:
            conflicts_in_cat = grouped[cat]
            if not conflicts_in_cat:
                continue

            cat_label = QLabel(category_labels.get(cat, cat.title()))
            cat_label.setStyleSheet(
                "font-weight: bold; color: #b0b0e0; font-size: 13px; margin-top: 8px;"
            )
            c_layout.addWidget(cat_label)

            for conflict in conflicts_in_cat:
                ann = conflict.get("annotation", {})
                game_crc = conflict.get("game_crc", "")
                processor = conflict.get("processor", "EE")
                address = conflict.get("address", "")
                triple = (game_crc, processor, address)

                mod_a = self.db.get(conflict.get("mod_a_id", ""))
                mod_b = self.db.get(conflict.get("mod_b_id", ""))

                frame = QFrame()
                frame.setObjectName("card")
                frame.setStyleSheet(
                    "QFrame#card { border: 1px solid #303070; background: #111128; }"
                )
                f_lay = QVBoxLayout(frame)
                f_lay.setSpacing(4)

                # --- Description row ---
                desc = ann.get("description")
                if desc:
                    desc_lbl = QLabel(f"📋  {desc}")
                    desc_lbl.setStyleSheet(
                        "color: #d0d0f8; font-size: 13px; font-weight: bold;"
                    )
                    desc_lbl.setWordWrap(True)
                    f_lay.addWidget(desc_lbl)

                addr_row = QHBoxLayout()
                crc_lbl = QLabel(f"CRC {game_crc}")
                crc_lbl.setStyleSheet("color: #505070; font-size: 10px; font-family: monospace;")
                addr_row.addWidget(crc_lbl)
                proc_lbl = QLabel(processor)
                proc_lbl.setStyleSheet("color: #505090; font-size: 10px; font-family: monospace;")
                addr_row.addWidget(proc_lbl)
                addr_lbl = QLabel(f"0x{address}")
                addr_lbl.setStyleSheet("color: #a09030; font-family: monospace; font-size: 11px;")
                addr_row.addWidget(addr_lbl)
                addr_row.addStretch()
                f_lay.addLayout(addr_row)

                if ann.get("inferred"):
                    inferred_lbl = QLabel(
                        f"  ⚙  Inferred category: {cat} — no specific description available for this address"
                    )
                    inferred_lbl.setStyleSheet("color: #707070; font-size: 10px; font-style: italic;")
                    f_lay.addWidget(inferred_lbl)

                # --- Radio buttons for each option ---
                from PyQt6.QtWidgets import QRadioButton, QButtonGroup
                btn_group = QButtonGroup(frame)
                radio_map = {}

                for mod, val_key in [(mod_a, "value_a"), (mod_b, "value_b")]:
                    if not mod:
                        continue
                    raw_val = conflict.get(val_key, "")
                    val_note = ann.get("value_note", f"0x{raw_val}")
                    # Show value interpretation from DB if available
                    from src.core.pnach_analyzer import describe_patch as dp2
                    ann2 = dp2(game_crc, processor, address, raw_val)
                    val_note2 = ann2.get("value_note", f"0x{raw_val}")

                    radio = QRadioButton(
                        f"  {mod.name}  —  value 0x{raw_val}  ({val_note2})"
                    )
                    radio.setStyleSheet("color: #c0c0e8; font-size: 12px;")
                    btn_group.addButton(radio)
                    radio_map[mod.id] = radio
                    f_lay.addWidget(radio)

                # Default: first option selected
                if radio_map:
                    list(radio_map.values())[0].setChecked(True)

                self._radio_groups[triple] = (radio_map, btn_group)
                c_layout.addWidget(frame)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # --- Buttons ---
        btns = QHBoxLayout()
        btns.addStretch()

        help_btn = QPushButton("❓ What does each value do?")
        help_btn.setObjectName("primary_btn")
        help_btn.clicked.connect(self._show_value_help)
        btns.addWidget(help_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        merge_btn = QPushButton("✅ Merge Selected Codes")
        merge_btn.setObjectName("success_btn")
        merge_btn.clicked.connect(self._on_merge)
        btns.addWidget(merge_btn)

        layout.addLayout(btns)

        self._dest_dir: str = ""

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _show_value_help(self):
        """Show a plain-language explanation for the selected conflict."""
        lines = []
        for triple, (radio_map, _) in self._radio_groups.items():
            game_crc, processor, address = triple
            from src.core.pnach_analyzer import describe_address, describe_patch
            desc = describe_address(game_crc, processor, address)
            if desc:
                lines.append(f"<b>0x{address}</b> ({processor}): {desc}")
        if lines:
            QMessageBox.information(
                self,
                "Address Descriptions",
                "<br>".join(lines) if lines else "No descriptions available.",
            )
        else:
            QMessageBox.information(
                self,
                "Address Descriptions",
                "No specific descriptions are available for these addresses.\n"
                "The analyzer uses heuristics to categorize unknown addresses.",
            )

    def _on_merge(self):
        from PyQt6.QtWidgets import QFileDialog as _FD
        dest = _FD.getExistingDirectory(self, "Choose output folder for merged PNACH")
        if not dest:
            return
        self._dest_dir = dest
        self.accept()

    def get_choices(self) -> dict:
        """Return {(game_crc, processor, address): winning_mod_id}."""
        choices = {}
        for triple, (radio_map, _) in self._radio_groups.items():
            for mod_id, radio in radio_map.items():
                if radio.isChecked():
                    choices[triple] = mod_id
                    break
        return choices

    def dest_dir(self) -> str:
        return self._dest_dir

    def write_merged(self) -> list:
        """Build merged PNACH files according to user choices.

        Returns a list of written file paths.
        """
        from src.core.pnach import parse_pnach, write_pnach, PnachFile, PatchLine
        from pathlib import Path as _P
        import tempfile

        choices = self.get_choices()
        dest = self._dest_dir
        if not dest:
            return []

        # Collect all PNACH files from all involved mods
        all_mod_ids = set()
        for c in self.pnach_conflicts:
            all_mod_ids.add(c.get("mod_a_id", ""))
            all_mod_ids.add(c.get("mod_b_id", ""))
        all_mod_ids.discard("")

        # Map CRC → {(processor, address): winning PatchLine}
        crc_patches: dict = {}

        for mod_id in all_mod_ids:
            mod = self.db.get(mod_id)
            if not mod:
                continue
            src = _P(mod.path)
            pnach_files = (
                list(src.rglob("*.pnach")) if src.is_dir()
                else [src] if src.suffix.lower() == ".pnach" else []
            )
            for pf_path in pnach_files:
                try:
                    pf = parse_pnach(str(pf_path))
                except Exception:
                    continue
                crc = pf.game_crc
                if crc not in crc_patches:
                    crc_patches[crc] = {"title": pf.game_title, "patches": {}}

                for patch in pf.patches:
                    if not patch.enabled:
                        continue
                    key = (patch.processor.upper(), patch.address.upper())
                    # Check if this address is a conflict
                    conflict_triple = (crc, patch.processor.upper(), patch.address.upper())
                    if conflict_triple in choices:
                        # Only include this patch if this mod was chosen for this address
                        if choices[conflict_triple] == mod_id:
                            crc_patches[crc]["patches"][key] = patch
                    else:
                        # Non-conflicting: include from first mod that provides it
                        if key not in crc_patches[crc]["patches"]:
                            crc_patches[crc]["patches"][key] = patch

        # Write merged PNACHs
        written = []
        for crc, info in crc_patches.items():
            patches = sorted(info["patches"].values(), key=lambda p: p.address)
            merged_pf = PnachFile(
                game_crc=crc,
                game_title=info.get("title", ""),
                header_comments=[
                    "// Custom merged PNACH created by PS2 Mod Manager",
                    "// Conflicting addresses resolved via PNACH Code Picker",
                ],
                patches=patches,
            )
            out_path = str(_P(dest) / f"{crc}.pnach")
            write_pnach(merged_pf, out_path)
            written.append(out_path)

        return written


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
    filter_by_author = pyqtSignal(str)     # author name — quick "see more by" filter

    def __init__(
        self,
        mod: ModInfo,
        has_conflict: bool = False,
        is_shadowed: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.mod = mod
        self.has_conflict = has_conflict
        self.is_shadowed = is_shadowed
        self._build_ui()

    def _build_ui(self):
        if self.is_shadowed:
            self.setObjectName("mod_item_shadowed")
        elif self.has_conflict:
            self.setObjectName("mod_item_conflict")
        else:
            self.setObjectName("mod_item")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(10)

        # Type icon
        icon_lbl = QLabel(_icon_for_type(self.mod.mod_type))
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 20px; opacity: 0.4;" if self.is_shadowed else "font-size: 20px;"
        )
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
        name_color = "#808080" if self.is_shadowed else "#ffffff"
        name_lbl = QLabel(self.mod.name)
        name_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {name_color};"
        )
        name_row.addWidget(name_lbl)

        if self.is_shadowed:
            shadow_badge = QLabel("🚫 Completely Shadowed")
            shadow_badge.setStyleSheet(
                "background:#303030; color:#909090; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            shadow_badge.setToolTip(
                "Every file in this mod is overridden by a higher-priority mod.\n"
                "It will have no effect when deployed. Raise its priority or disable\n"
                "the conflicting higher-priority mod to restore it."
            )
            name_row.addWidget(shadow_badge)

        if self.has_conflict and not self.is_shadowed:
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
        meta_lbl.setStyleSheet("color: #505070; font-size: 11px;" if self.is_shadowed else "color: #7070a0; font-size: 11px;")
        info.addWidget(meta_lbl)

        if self.mod.description:
            desc = QLabel(textwrap.shorten(self.mod.description, width=100, placeholder="…"))
            desc.setStyleSheet("color: #606070; font-size: 11px;" if self.is_shadowed else "color: #9090b0; font-size: 11px;")
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

        if self.mod.author and self.mod.author != "Unknown":
            author_btn = QPushButton("👤")
            author_btn.setFixedSize(28, 28)
            author_btn.setToolTip(f"See more by {self.mod.author}")
            author_btn.clicked.connect(lambda: self.filter_by_author.emit(self.mod.author))
            btn_col.addWidget(author_btn)

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

    # Emitted when the user clicks "See more by [author]" — (author, mod_type_or_None)
    see_more_by_author = pyqtSignal(str, object)

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

        # ── Author quick-nav row ──────────────────────────────────────────
        if self.mod.author and self.mod.author != "Unknown":
            from src.models.mod import ModType as _MT
            author_nav_row = QHBoxLayout()
            author_nav_row.setSpacing(6)

            see_more_btn = QPushButton(f"👤 See more by {self.mod.author}")
            see_more_btn.setToolTip(
                f"Filter the current panel to show only mods by {self.mod.author}"
            )
            see_more_btn.clicked.connect(
                lambda: (
                    self.see_more_by_author.emit(self.mod.author, self.mod.mod_type),
                    self.accept(),
                )
            )
            author_nav_row.addWidget(see_more_btn)

            # "See PNACH by this author" — only if current type is not already PNACH
            if self.mod.mod_type not in (_MT.PNACH, _MT.CHEAT):
                pnach_btn = QPushButton(f"🔧 Find PNACH by {self.mod.author}")
                pnach_btn.setToolTip(
                    f"Switch to the PNACH panel and filter by {self.mod.author}"
                )
                pnach_btn.clicked.connect(
                    lambda: (
                        self.see_more_by_author.emit(self.mod.author, _MT.PNACH),
                        self.accept(),
                    )
                )
                author_nav_row.addWidget(pnach_btn)

            # "See textures by this author" — only if current type is not already TEXTURE
            if self.mod.mod_type != _MT.TEXTURE_PACK:
                tex_btn = QPushButton(f"🎨 Find textures by {self.mod.author}")
                tex_btn.setToolTip(
                    f"Switch to the Texture Packs panel and filter by {self.mod.author}"
                )
                tex_btn.clicked.connect(
                    lambda: (
                        self.see_more_by_author.emit(self.mod.author, _MT.TEXTURE_PACK),
                        self.accept(),
                    )
                )
                author_nav_row.addWidget(tex_btn)

            author_nav_row.addStretch()
            layout.addLayout(author_nav_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ---------------------------------------------------------------------------
# Texture File Picker Dialog
# ---------------------------------------------------------------------------

class TextureFilePickerDialog(QDialog):
    """Let the user resolve texture-pack file conflicts by choosing, for every
    conflicting relative path, which mod's file they want to deploy.

    Non-conflicting files from **all** selected mods are always included.
    After the dialog is accepted, call :meth:`write_merged` to copy the
    chosen files into an output folder that can be used as a new mod.
    """

    def __init__(self, conflicts: list, db, parent=None):
        """
        *conflicts* — list of :class:`~src.models.mod.ConflictInfo` objects
            (texture-pack file-level conflicts from ``ModManager.detect_conflicts()``).
        *db* — ``ModDatabase`` instance.
        """
        super().__init__(parent)
        self.conflicts = conflicts
        self.db = db
        self.setWindowTitle("🎨 Texture File Picker — Build Custom Merged Texture Pack")
        self.setMinimumSize(860, 600)
        # Map (mod_a_id, mod_b_id, rel_file) → winning mod_id
        self._choices: dict = {}
        self._dest_dir: str = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        from pathlib import Path as _P
        from collections import defaultdict

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        header = QLabel("🎨  Build Your Own Merged Texture Pack")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #b0e0ff;")
        layout.addWidget(header)

        intro = QLabel(
            "For each conflicting texture file, choose which mod's version you want to use.\n"
            "All non-conflicting files from every selected mod are automatically included.\n"
            "Click 'A wins all' / 'B wins all' to quickly resolve all files for a pair at once."
        )
        intro.setStyleSheet("color: #9090b0; font-size: 12px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(12)

        self._radio_rows: dict = {}  # (mod_a_id, mod_b_id, rel_file) → {mod_id: QRadioButton}

        for conflict in self.conflicts:
            mod_a = self.db.get(conflict.mod_a_id)
            mod_b = self.db.get(conflict.mod_b_id)
            if not mod_a or not mod_b:
                continue

            pair_frame = QFrame()
            pair_frame.setObjectName("card")
            pair_frame.setStyleSheet(
                "QFrame#card { border: 1px solid #204070; background: #0d1020; "
                "border-radius: 6px; padding: 4px; }"
            )
            p_layout = QVBoxLayout(pair_frame)
            p_layout.setSpacing(6)

            # --- Pair header ---
            pair_header_row = QHBoxLayout()
            pair_lbl = QLabel(f"🔴  {mod_a.name}  ↔  {mod_b.name}")
            pair_lbl.setStyleSheet("font-weight: bold; color: #e080a0; font-size: 13px;")
            pair_header_row.addWidget(pair_lbl, 1)

            # "A wins all" / "B wins all" quick-resolve
            from PyQt6.QtWidgets import QButtonGroup as _QBG
            a_all_btn = QPushButton(f"✅ {mod_a.name} wins all")
            a_all_btn.setObjectName("success_btn")
            a_all_btn.setFixedHeight(24)
            b_all_btn = QPushButton(f"✅ {mod_b.name} wins all")
            b_all_btn.setObjectName("success_btn")
            b_all_btn.setFixedHeight(24)

            def _make_all_winner(ma, mb, files, pick):
                def _do():
                    for rf in files:
                        triple = (ma.id, mb.id, rf)
                        rmap = self._radio_rows.get(triple, {})
                        winner = ma.id if pick == "a" else mb.id
                        if winner in rmap:
                            rmap[winner].setChecked(True)
                return _do

            a_all_btn.clicked.connect(
                _make_all_winner(mod_a, mod_b, conflict.conflicting_files, "a")
            )
            b_all_btn.clicked.connect(
                _make_all_winner(mod_a, mod_b, conflict.conflicting_files, "b")
            )

            pair_header_row.addWidget(a_all_btn)
            pair_header_row.addWidget(b_all_btn)
            p_layout.addLayout(pair_header_row)

            files_count_lbl = QLabel(
                f"  {len(conflict.conflicting_files)} conflicting file(s)"
            )
            files_count_lbl.setStyleSheet("color: #60608a; font-size: 11px;")
            p_layout.addWidget(files_count_lbl)

            # --- Per-file rows (inside collapsible) ---
            toggle_btn = QPushButton(
                f"▶  Show per-file choices ({len(conflict.conflicting_files)} files)"
            )
            toggle_btn.setCheckable(True)
            toggle_btn.setStyleSheet(
                "background: transparent; color: #6090d0; border: none; "
                "text-align: left; font-size: 12px;"
            )
            p_layout.addWidget(toggle_btn)

            per_file_widget = QWidget()
            per_file_widget.setVisible(False)
            pf_v = QVBoxLayout(per_file_widget)
            pf_v.setSpacing(4)
            pf_v.setContentsMargins(10, 4, 4, 4)

            display_files = conflict.conflicting_files[:50]
            for rel_file in display_files:
                triple = (mod_a.id, mod_b.id, rel_file)
                row_w = QWidget()
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(0, 0, 0, 0)
                row_h.setSpacing(6)

                fname_lbl = QLabel(_P(rel_file).name)
                fname_lbl.setStyleSheet(
                    "color: #a0a0c0; font-size: 11px; font-family: monospace;"
                )
                fname_lbl.setToolTip(rel_file)
                fname_lbl.setFixedWidth(240)
                row_h.addWidget(fname_lbl)

                from PyQt6.QtWidgets import QRadioButton as _QRB
                btn_group = _QBG(row_w)
                radio_map = {}

                for mod in (mod_a, mod_b):
                    rb = _QRB(mod.name)
                    rb.setStyleSheet("color: #c0c0e8; font-size: 11px;")
                    btn_group.addButton(rb)
                    radio_map[mod.id] = rb
                    row_h.addWidget(rb)

                row_h.addStretch()
                # Default: mod_a wins
                list(radio_map.values())[0].setChecked(True)
                self._radio_rows[triple] = radio_map
                pf_v.addWidget(row_w)

            if len(conflict.conflicting_files) > 50:
                more_lbl = QLabel(
                    f"  … and {len(conflict.conflicting_files) - 50} more files. "
                    "Use 'wins all' buttons above to resolve them all at once."
                )
                more_lbl.setStyleSheet("color: #606080; font-size: 10px; font-style: italic;")
                pf_v.addWidget(more_lbl)
                # Default all extra files to mod_a
                for rf in conflict.conflicting_files[50:]:
                    triple = (mod_a.id, mod_b.id, rf)
                    self._radio_rows[triple] = {mod_a.id: None, "_default": mod_a.id}

            per_file_widget.setLayout(pf_v)
            p_layout.addWidget(per_file_widget)

            def _toggle_files(checked, w=per_file_widget, btn=toggle_btn, n=len(conflict.conflicting_files)):
                w.setVisible(checked)
                btn.setText(
                    f"{'▼' if checked else '▶'}  Show per-file choices ({n} files)"
                )

            toggle_btn.toggled.connect(_toggle_files)
            c_layout.addWidget(pair_frame)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        merge_btn = QPushButton("✅ Copy Selected Files to Folder")
        merge_btn.setObjectName("success_btn")
        merge_btn.clicked.connect(self._on_merge)
        btn_row.addWidget(merge_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_merge(self):
        from PyQt6.QtWidgets import QFileDialog as _FD
        dest = _FD.getExistingDirectory(self, "Choose output folder for merged texture pack")
        if not dest:
            return
        self._dest_dir = dest
        self.accept()

    def get_file_choices(self) -> dict:
        """Return {(mod_a_id, mod_b_id, rel_file): winning_mod_id}."""
        choices = {}
        for triple, radio_map in self._radio_rows.items():
            if "_default" in radio_map:
                choices[triple] = radio_map["_default"]
                continue
            for mod_id, rb in radio_map.items():
                if rb is not None and rb.isChecked():
                    choices[triple] = mod_id
                    break
        return choices

    def dest_dir(self) -> str:
        return self._dest_dir

    def write_merged(self) -> dict:
        """Copy selected texture files to *dest_dir*.

        Returns a dict with:
          ``"copied"``  — number of files copied
          ``"skipped"`` — number skipped (missing source)
          ``"dest"``    — destination folder path
        """
        import shutil
        from pathlib import Path as _P

        choices = self.get_file_choices()
        dest = _P(self._dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        # Collect all involved mod IDs
        all_mod_ids: set = set()
        for conflict in self.conflicts:
            all_mod_ids.add(conflict.mod_a_id)
            all_mod_ids.add(conflict.mod_b_id)

        # Track which relative paths have been resolved by the choices map
        resolved_paths: dict = {}  # rel_path → winning_mod_id
        for (ma_id, mb_id, rel_file), winner_id in choices.items():
            resolved_paths[rel_file] = winner_id

        copied = 0
        skipped = 0

        for mod_id in all_mod_ids:
            mod = self.db.get(mod_id)
            if not mod:
                continue
            src_root = _P(mod.path)
            for rel_file in (mod.files or []):
                # If this file is a conflict, only copy the winner
                if rel_file in resolved_paths:
                    if resolved_paths[rel_file] != mod_id:
                        continue  # this mod lost the conflict
                src_file = src_root / rel_file
                if not src_file.is_file():
                    skipped += 1
                    continue
                dest_file = dest / rel_file
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(dest_file))
                copied += 1

        return {"copied": copied, "skipped": skipped, "dest": str(dest)}


# ---------------------------------------------------------------------------
# Conflict Resolution Dialog
# ---------------------------------------------------------------------------

class ConflictDialog(QDialog):
    """Shows conflicts and lets the user choose resolution."""

    def __init__(self, conflicts: list, db, parent=None, pnach_conflicts: list = None):
        super().__init__(parent)
        self.conflicts = conflicts
        self.pnach_conflicts = pnach_conflicts or []
        self.db = db
        total = len(conflicts) + len(self.pnach_conflicts)
        self.setWindowTitle(f"Mod Conflicts Detected ({total})")
        self.setMinimumSize(740, 560)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        n_file = len(self.conflicts)
        n_pnach = len(self.pnach_conflicts)
        parts = []
        if n_file:
            parts.append(f"{n_file} file conflict(s)")
        if n_pnach:
            parts.append(f"{n_pnach} PNACH address conflict(s)")
        summary_str = "  •  ".join(parts) if parts else "conflicts"

        header = QLabel(f"⚠  {summary_str} detected between enabled mods")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff8080;")
        layout.addWidget(header)

        sub = QLabel(
            "Choose which mod wins each conflict. You can resolve all files at once,\n"
            "or expand a conflict to pick winners file-by-file."
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

            # ── Header row ──────────────────────────────────────────────
            title = QLabel(f"🔴  {mod_a.name}  ↔  {mod_b.name}")
            title.setStyleSheet("font-weight: bold; color: #ff8080;")
            f_layout.addWidget(title)

            count_lbl = QLabel(
                f"{len(conflict.conflicting_files)} conflicting file(s)"
            )
            count_lbl.setStyleSheet("color: #9090b0; font-size: 11px;")
            f_layout.addWidget(count_lbl)

            # ── Quick-resolve: entire conflict ───────────────────────────
            quick_row = QHBoxLayout()
            a_wins = QPushButton(f"✅ {mod_a.name} wins all")
            a_wins.setObjectName("success_btn")
            b_wins = QPushButton(f"✅ {mod_b.name} wins all")
            b_wins.setObjectName("success_btn")
            ignore_btn = QPushButton("⚡ Allow both (⚠ unexpected effects)")
            ignore_btn.setObjectName("primary_btn")

            def _make_whole_resolver(ma, mb, which):
                def _resolve():
                    if which == "a":
                        ma.priority = max(ma.priority, mb.priority) + 1
                        self.db.update(ma)
                    elif which == "b":
                        mb.priority = max(ma.priority, mb.priority) + 1
                        self.db.update(mb)
                return _resolve

            a_wins.clicked.connect(_make_whole_resolver(mod_a, mod_b, "a"))
            b_wins.clicked.connect(_make_whole_resolver(mod_a, mod_b, "b"))

            quick_row.addWidget(a_wins)
            quick_row.addWidget(b_wins)
            quick_row.addWidget(ignore_btn)
            f_layout.addLayout(quick_row)

            # ── "Disable loser" resolution row ──────────────────────────
            disable_row = QHBoxLayout()
            disable_a_btn = QPushButton(f"🚫 Disable '{mod_a.name}'")
            disable_a_btn.setStyleSheet(
                "background:#2a0a0a; color:#d06060; border-radius:4px; font-size:10px;"
            )
            disable_b_btn = QPushButton(f"🚫 Disable '{mod_b.name}'")
            disable_b_btn.setStyleSheet(
                "background:#2a0a0a; color:#d06060; border-radius:4px; font-size:10px;"
            )

            def _make_disable_resolver(target_mod):
                def _resolve():
                    target_mod.enabled = False
                    self.db.update(target_mod)
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "Conflict Resolved",
                        f"'{target_mod.name}' has been disabled.\n"
                        "Re-enable it any time from the mod panel.",
                    )
                return _resolve

            disable_a_btn.clicked.connect(_make_disable_resolver(mod_a))
            disable_b_btn.clicked.connect(_make_disable_resolver(mod_b))
            disable_row.addWidget(QLabel("Or disable one mod:"))
            disable_row.addWidget(disable_a_btn)
            disable_row.addWidget(disable_b_btn)
            disable_row.addStretch()
            f_layout.addLayout(disable_row)

            # ── Per-file resolution (expandable) ────────────────────────
            if conflict.conflicting_files:
                toggle_btn = QPushButton(
                    f"▶  Per-file resolution ({len(conflict.conflicting_files)} files)"
                )
                toggle_btn.setCheckable(True)
                toggle_btn.setStyleSheet(
                    "background: transparent; color: #6090d0; border: none; text-align: left;"
                )

                per_file_container = QWidget()
                per_file_container.setVisible(False)
                pf_layout = QVBoxLayout(per_file_container)
                pf_layout.setContentsMargins(12, 4, 4, 4)
                pf_layout.setSpacing(4)

                for rel_file in conflict.conflicting_files[:20]:  # cap at 20 for UI
                    row = QHBoxLayout()
                    fname_lbl = QLabel(rel_file)
                    fname_lbl.setStyleSheet(
                        "color: #808090; font-size: 11px; font-family: monospace;"
                    )
                    fname_lbl.setToolTip(rel_file)
                    row.addWidget(fname_lbl, 1)

                    def _make_file_resolver(ma, mb, f):
                        def _resolve_a():
                            # Ensure ma has higher priority than mb
                            if ma.priority <= mb.priority:
                                ma.priority = mb.priority + 1
                                self.db.update(ma)
                        def _resolve_b():
                            if mb.priority <= ma.priority:
                                mb.priority = ma.priority + 1
                                self.db.update(mb)
                        return _resolve_a, _resolve_b

                    ra, rb = _make_file_resolver(mod_a, mod_b, rel_file)
                    fa_btn = QPushButton(f"A")
                    fa_btn.setFixedWidth(30)
                    fa_btn.setToolTip(f"{mod_a.name} wins this file")
                    fa_btn.setStyleSheet(
                        "background:#1a4a1a; color:#60c060; border-radius:4px; padding:2px 4px;"
                    )
                    fa_btn.clicked.connect(ra)
                    fb_btn = QPushButton(f"B")
                    fb_btn.setFixedWidth(30)
                    fb_btn.setToolTip(f"{mod_b.name} wins this file")
                    fb_btn.setStyleSheet(
                        "background:#1a1a4a; color:#6060c0; border-radius:4px; padding:2px 4px;"
                    )
                    fb_btn.clicked.connect(rb)

                    row.addWidget(fa_btn)
                    row.addWidget(fb_btn)
                    pf_layout.addLayout(row)

                if len(conflict.conflicting_files) > 20:
                    pf_layout.addWidget(
                        QLabel(
                            f"  … and {len(conflict.conflicting_files) - 20} more files "
                            "(use 'wins all' buttons above for bulk resolution)"
                        )
                    )

                def _toggle_expanded(checked, container=per_file_container, btn=toggle_btn):
                    container.setVisible(checked)
                    btn.setText(
                        (f"▼  Per-file resolution ({len(conflict.conflicting_files)} files)"
                         if checked else
                         f"▶  Per-file resolution ({len(conflict.conflicting_files)} files)")
                    )

                toggle_btn.toggled.connect(_toggle_expanded)
                f_layout.addWidget(toggle_btn)
                f_layout.addWidget(per_file_container)

            c_layout.addWidget(frame)

        # ── PNACH address-level conflicts ────────────────────────────────
        if self.pnach_conflicts:
            pnach_sep = QFrame()
            pnach_sep.setFrameShape(QFrame.Shape.HLine)
            pnach_sep.setStyleSheet("color: #3a3060; margin-top: 8px;")
            c_layout.addWidget(pnach_sep)

            pnach_header = QLabel("🔧  PNACH Address Conflicts")
            pnach_header.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #e0a030; margin-top: 4px;"
            )
            c_layout.addWidget(pnach_header)

            pnach_sub = QLabel(
                "The following PNACH mods write different values to the same memory address.\n"
                "Only one value can take effect. Raise a mod's priority to let it win."
            )
            pnach_sub.setStyleSheet("color: #9090b0; font-size: 11px;")
            pnach_sub.setWordWrap(True)
            c_layout.addWidget(pnach_sub)

            # Group by (mod_a, mod_b) pair for cleaner display
            from collections import defaultdict
            pnach_by_pair: dict = defaultdict(list)
            for pc in self.pnach_conflicts:
                pair = tuple(sorted([pc["mod_a_id"], pc["mod_b_id"]]))
                pnach_by_pair[pair].append(pc)

            for (id_a, id_b), entries in pnach_by_pair.items():
                mod_a = self.db.get(id_a)
                mod_b = self.db.get(id_b)
                if not mod_a or not mod_b:
                    continue

                pf = QFrame()
                pf.setObjectName("card")
                pf.setStyleSheet(
                    "QFrame#card { border: 1px solid #5a3010; background: #1e1208; }"
                )
                pf_layout = QVBoxLayout(pf)

                pf_title = QLabel(
                    f"🟠  {mod_a.name}  ↔  {mod_b.name}"
                    f"  —  {len(entries)} address conflict(s)"
                )
                pf_title.setStyleSheet("font-weight: bold; color: #e0a030; font-size: 12px;")
                pf_layout.addWidget(pf_title)

                # Quick-resolve buttons
                pq_row = QHBoxLayout()
                pa_wins = QPushButton(f"✅ {mod_a.name} wins")
                pa_wins.setObjectName("success_btn")
                pb_wins = QPushButton(f"✅ {mod_b.name} wins")
                pb_wins.setObjectName("success_btn")

                def _make_pnach_resolver(ma, mb, which):
                    def _resolve():
                        if which == "a":
                            ma.priority = max(ma.priority, mb.priority) + 1
                            self.db.update(ma)
                        else:
                            mb.priority = max(ma.priority, mb.priority) + 1
                            self.db.update(mb)
                    return _resolve

                pa_wins.clicked.connect(_make_pnach_resolver(mod_a, mod_b, "a"))
                pb_wins.clicked.connect(_make_pnach_resolver(mod_a, mod_b, "b"))
                pq_row.addWidget(pa_wins)
                pq_row.addWidget(pb_wins)
                pq_row.addStretch()
                pf_layout.addLayout(pq_row)

                # Expandable address list
                addr_toggle = QPushButton(
                    f"▶  Show conflicting addresses ({len(entries)})"
                )
                addr_toggle.setCheckable(True)
                addr_toggle.setStyleSheet(
                    "background: transparent; color: #c08030; border: none; text-align: left;"
                )

                addr_container = QWidget()
                addr_container.setVisible(False)
                al = QVBoxLayout(addr_container)
                al.setContentsMargins(12, 2, 4, 2)
                al.setSpacing(2)

                for entry in entries[:20]:
                    ar = QHBoxLayout()
                    crc_lbl = QLabel(f"CRC {entry.get('game_crc', '?')}")
                    crc_lbl.setStyleSheet("color: #606060; font-size: 10px; font-family: monospace;")
                    crc_lbl.setFixedWidth(90)
                    ar.addWidget(crc_lbl)

                    proc_lbl = QLabel(entry.get("processor", "EE"))
                    proc_lbl.setStyleSheet("color: #606090; font-size: 10px; font-family: monospace;")
                    proc_lbl.setFixedWidth(30)
                    ar.addWidget(proc_lbl)

                    addr_lbl = QLabel(f"0x{entry.get('address', '?')}")
                    addr_lbl.setStyleSheet("color: #a09040; font-family: monospace; font-size: 11px;")
                    addr_lbl.setFixedWidth(110)
                    ar.addWidget(addr_lbl)

                    val_a_lbl = QLabel(f"A: {entry.get('value_a', '?')}")
                    val_a_lbl.setStyleSheet("color: #60a060; font-size: 10px; font-family: monospace;")
                    val_a_lbl.setFixedWidth(100)
                    ar.addWidget(val_a_lbl)

                    val_b_lbl = QLabel(f"B: {entry.get('value_b', '?')}")
                    val_b_lbl.setStyleSheet("color: #6060a0; font-size: 10px; font-family: monospace;")
                    val_b_lbl.setFixedWidth(100)
                    ar.addWidget(val_b_lbl)

                    ar.addStretch()
                    al.addLayout(ar)

                if len(entries) > 20:
                    al.addWidget(QLabel(f"  … and {len(entries) - 20} more addresses"))

                def _toggle_addrs(checked, c=addr_container, b=addr_toggle, n=len(entries)):
                    c.setVisible(checked)
                    b.setText(
                        f"▼  Show conflicting addresses ({n})" if checked
                        else f"▶  Show conflicting addresses ({n})"
                    )

                addr_toggle.toggled.connect(_toggle_addrs)
                pf_layout.addWidget(addr_toggle)
                pf_layout.addWidget(addr_container)

                c_layout.addWidget(pf)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Button row: Texture Picker + Code Picker + Close
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        if self.conflicts:
            tex_picker_btn = QPushButton("🎨 Open Texture File Picker — build custom merged texture pack")
            tex_picker_btn.setObjectName("primary_btn")
            tex_picker_btn.setToolTip(
                "Opens the Texture File Picker where you can choose exactly which mod's "
                "file wins for each conflicting texture, then export a merged texture pack folder."
            )
            tex_picker_btn.clicked.connect(self._open_texture_picker)
            btn_row.addWidget(tex_picker_btn)

        if self.pnach_conflicts:
            picker_btn = QPushButton("🔧 Open Code Picker — build custom merged PNACH")
            picker_btn.setObjectName("primary_btn")
            picker_btn.setToolTip(
                "Opens the PNACH Code Picker where you can choose exactly which "
                "code wins for each conflicting address and merge them into a single patch."
            )
            picker_btn.clicked.connect(self._open_code_picker)
            btn_row.addWidget(picker_btn)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _open_texture_picker(self):
        from src.ui.widgets import TextureFilePickerDialog
        dlg = TextureFilePickerDialog(self.conflicts, self.db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.write_merged()
            dest = result.get("dest", "")
            copied = result.get("copied", 0)
            skipped = result.get("skipped", 0)
            if dest:
                msg = (
                    f"✅  Merged texture pack written to:\n{dest}\n\n"
                    f"Files copied: {copied}"
                )
                if skipped:
                    msg += f"\nFiles skipped (missing source): {skipped}"
                msg += "\n\nImport the folder from the Texture Packs panel."
                QMessageBox.information(self, "Texture Pack Merged", msg)
            else:
                QMessageBox.warning(self, "Nothing Written",
                                    "No files were copied. Choose an output folder.")

    def _open_code_picker(self):
        from src.ui.widgets import PnachCodePickerDialog
        dlg = PnachCodePickerDialog(self.pnach_conflicts, self.db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            written = dlg.write_merged()
            if written:
                QMessageBox.information(
                    self,
                    "Merged PNACH Written",
                    f"✅  Wrote {len(written)} merged PNACH file(s):\n\n"
                    + "\n".join(written)
                    + "\n\nImport the merged file(s) from the PNACH panel.",
                )
            else:
                QMessageBox.warning(self, "Nothing Written",
                                    "No PNACH files were written. Choose an output folder.")


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


# ---------------------------------------------------------------------------
# PnachCodeBuilderDialog
# ---------------------------------------------------------------------------

class PnachCodeBuilderDialog(QDialog):
    """Interactive PNACH code builder that lets users select effects from the
    known-address DB for a specific game, choose preset values, detect
    conflicts, and write a merged ``.pnach`` file to the PCSX2 cheats folder.

    Usage::

        dlg = PnachCodeBuilderDialog(
            game_serial="SLUS-21028",
            cheats_dir="/path/to/pcsx2/cheats",
            parent=self,
        )
        dlg.exec()
    """

    def __init__(
        self,
        game_serial: str = "",
        cheats_dir: str = "",
        config=None,
        parent=None,
    ):
        super().__init__(parent)
        self._game_serial = game_serial.strip().upper()
        self._cheats_dir = cheats_dir
        self._config = config
        self._patch_widgets: list = []  # list of (key, addr_widget)
        self.setWindowTitle("🧩 PNACH Code Builder — Apply DB Effects to Game")
        self.setMinimumSize(860, 600)
        self.resize(920, 680)
        self._build_ui()
        if self._game_serial:
            self._load_game(self._game_serial)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        from PyQt6.QtWidgets import QComboBox, QGroupBox, QRadioButton, QButtonGroup, QSplitter

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        hdr = QLabel("🧩  PNACH Code Builder")
        hdr.setStyleSheet("font-size: 17px; font-weight: bold; color: #70b0ff;")
        layout.addWidget(hdr)

        intro = QLabel(
            "Select a game, tick the effects you want, then choose a value from the dropdown\n"
            "(or type a custom number for money/speed/etc.)  Click Install when ready."
        )
        intro.setStyleSheet("color: #9090b0; font-size: 12px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Game picker row
        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_lbl = QLabel("Game:")
        game_lbl.setStyleSheet("color: #c0c0e0; font-weight: bold;")
        game_row.addWidget(game_lbl)

        self._game_combo = QComboBox()
        self._game_combo.setMinimumWidth(350)
        self._game_combo.setEditable(True)
        self._game_combo.lineEdit().setPlaceholderText(
            "Type game name or serial to search…"
        )
        self._populate_game_combo()
        # Connect text changes for live search filtering
        self._game_combo.lineEdit().textEdited.connect(self._on_game_search)
        game_row.addWidget(self._game_combo, 1)

        load_btn = QPushButton("Load Effects")
        load_btn.setObjectName("primary_btn")
        load_btn.clicked.connect(self._on_load_btn)
        game_row.addWidget(load_btn)
        layout.addLayout(game_row)

        # Verification summary banner (populated by _render_entries)
        self._verification_banner = QLabel("")
        self._verification_banner.setWordWrap(True)
        self._verification_banner.setStyleSheet(
            "background: #131828; border: 1px solid #2a3060;"
            " border-radius: 4px; padding: 5px 10px;"
            " color: #90a0c0; font-size: 11px;"
        )
        self._verification_banner.setVisible(False)
        layout.addWidget(self._verification_banner)

        # Scroll area for effect rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._effects_container = QWidget()
        self._effects_layout = QVBoxLayout(self._effects_container)
        self._effects_layout.setSpacing(6)
        self._effects_layout.setContentsMargins(0, 0, 0, 0)
        self._effects_layout.addStretch()
        self._scroll.setWidget(self._effects_container)
        layout.addWidget(self._scroll, 1)

        # Status / conflict bar
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #e0b060; font-size: 12px;")
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)

        # Cheats dir row
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("PCSX2 Cheats folder:")
        dir_lbl.setStyleSheet("color: #9090b0;")
        dir_row.addWidget(dir_lbl)
        self._dir_edit = QLineEdit(self._cheats_dir)
        self._dir_edit.setPlaceholderText("Path to PCSX2 cheats/ folder…")
        dir_row.addWidget(self._dir_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        preview_btn = QPushButton("🔍 Preview PNACH")
        preview_btn.clicked.connect(self._preview_pnach)
        btn_row.addWidget(preview_btn)
        install_btn = QPushButton("💾 Install to PCSX2")
        install_btn.setObjectName("primary_btn")
        install_btn.clicked.connect(self._install_pnach)
        btn_row.addWidget(install_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Game combo
    # ------------------------------------------------------------------

    def _populate_game_combo(self, filter_text: str = ""):
        """Populate (or re-filter) the game dropdown.

        Shows **library games first** (if a library path is configured), then
        all other known PS2 serials from the serial database (2000+ games).
        When *filter_text* is provided only entries whose title or serial
        contain the search string are shown (case-insensitive).
        """
        from src.core.pnach_analyzer import list_all_serials_in_db

        # ── Gather library serials ─────────────────────────────────────
        library_serials: frozenset = frozenset()
        try:
            lib_path = getattr(self._config, "game_library_path", "") or ""
            if lib_path:
                from src.core.game_library import get_library_serials
                library_serials = get_library_serials(lib_path)
        except Exception:
            pass

        # ── Build full serial→title mapping from serial DB ────────────
        all_serials: dict[str, str] = {}
        try:
            from src.core.serial_validator import SerialDatabase
            sdb = SerialDatabase()
            for title in sdb.all_titles():
                info = sdb.get_info(title)
                if info and info.serial:
                    all_serials[info.serial.upper()] = title
        except Exception:
            pass
        # Overlay pnach DB entries (may have CRC-only entries not in serial DB)
        for serial, title in list_all_serials_in_db():
            if serial not in all_serials:
                all_serials[serial] = title

        # ── Filter ────────────────────────────────────────────────────
        needle = filter_text.strip().lower()
        filtered = [
            (serial, title)
            for serial, title in all_serials.items()
            if not needle
            or needle in title.lower()
            or needle in serial.lower()
        ]

        # ── Sort: library games first, then alphabetical by title ─────
        def _sort_key(item):
            serial, title = item
            return (0 if serial in library_serials else 1, title.lower())

        filtered.sort(key=_sort_key)

        # ── Rebuild combo (preserve current selection) ─────────────────
        previously_selected = self._game_combo.currentData()
        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        if not needle:
            self._game_combo.addItem("— Select a game —", "")
        for serial, title in filtered:
            prefix = "📁 " if serial in library_serials else ""
            display = f"{prefix}{title}  ({serial})"
            self._game_combo.addItem(display, serial)

        # Restore previous selection if it still exists in filtered list
        if previously_selected:
            for i in range(self._game_combo.count()):
                if self._game_combo.itemData(i) == previously_selected:
                    self._game_combo.setCurrentIndex(i)
                    break
        elif self._game_serial:
            for i in range(self._game_combo.count()):
                if self._game_combo.itemData(i) == self._game_serial:
                    self._game_combo.setCurrentIndex(i)
                    break

        self._game_combo.blockSignals(False)

    def _on_game_search(self, text: str):
        """Called when the user types in the game combo — re-filter the list."""
        self._populate_game_combo(filter_text=text)
        # Reopen dropdown to show filtered results
        if text.strip():
            self._game_combo.showPopup()

    def _on_load_btn(self):
        """Load effects for the currently selected/typed game."""
        serial = self._game_combo.currentData()
        if not serial:
            # User may have typed a name fragment — try to extract the serial
            text = self._game_combo.currentText().strip()
            # Common format: "Title  (SERIAL)" — extract the part in parens
            import re as _re
            m = _re.search(r'\(([A-Z]{2,4}-\d{5})\)', text.upper())
            if m:
                serial = m.group(1)
            else:
                # Try interpreting the whole text as a serial
                from src.core.game_registry import is_valid_serial
                if is_valid_serial(text.upper()):
                    serial = text.upper()
        if serial and serial != "":
            self._load_game(serial)

    # ------------------------------------------------------------------
    # Load entries for the selected game
    # ------------------------------------------------------------------

    def _load_game(self, serial: str):
        from src.core.pnach_analyzer import entries_for_serial, get_game_verification_summary
        self._game_serial = serial.strip().upper()
        entries = entries_for_serial(self._game_serial)
        self._render_entries(entries)

        # Populate verification summary banner
        # Use any CRC found in the entries (all entries for a serial share a CRC)
        crc = ""
        for e in entries:
            crc = e.get("game_crc", "").upper()
            if crc:
                break

        if crc:
            summary = get_game_verification_summary(crc)
            vc      = summary["verification_counts"]
            cv      = vc.get("community_verified", 0) + vc.get("verified", 0)
            est     = vc.get("estimated", 0)
            nw      = vc.get("reported_not_working", 0)
            cw      = summary["code_method_counts"].get("continuous_write", 0)

            parts = [f"<b>{summary['game_title'] or self._game_serial}</b>"]
            if cv:
                parts.append(f"<span style='color:#50c070'>✅ {cv} verified</span>")
            if est:
                parts.append(f"<span style='color:#b0a040'>🔬 {est} estimated</span>")
            if nw:
                parts.append(f"<span style='color:#c04040'>❌ {nw} not working</span>")
            if cw:
                parts.append(
                    f"<span style='color:#e08030'>⟳ {cw} continuous-write "
                    "(game resets each frame — these codes must be re-applied every frame)</span>"
                )
            self._verification_banner.setText("  ·  ".join(parts))
            self._verification_banner.setVisible(True)
        else:
            self._verification_banner.setVisible(False)

    def _render_entries(self, entries: list):
        from PyQt6.QtWidgets import QGroupBox, QRadioButton, QButtonGroup, QComboBox as QCBox

        # Clear existing
        self._patch_widgets = []
        while self._effects_layout.count() > 1:
            item = self._effects_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            empty = QLabel(
                "No DB entries found for this game serial.\n"
                "Add addresses to data/pnach_db/known_addresses.json to enable this feature."
            )
            empty.setStyleSheet("color: #7070a0; font-size: 13px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._effects_layout.insertWidget(0, empty)
            self._status_lbl.setText("")
            return

        # Group by category
        CAT_LABELS = {
            "physics":    "⚡ Physics & Movement",
            "gameplay":   "🎮 Gameplay",
            "graphics":   "🖥️ Graphics & Display",
            "audio":      "🔊 Audio",
            "cheat":      "🌟 Cheats & Stats",
            "hardware_registers": "🔌 Hardware",
            "unknown":    "❓ Other",
        }
        cats: dict = {}
        for e in entries:
            c = e.get("category", "unknown")
            cats.setdefault(c, []).append(e)

        cat_order = ["physics", "gameplay", "graphics", "cheat", "audio",
                     "hardware_registers", "unknown"]
        ordered_cats = [c for c in cat_order if c in cats]
        ordered_cats += [c for c in cats if c not in ordered_cats]

        idx = 0
        for cat in ordered_cats:
            cat_lbl = QLabel(f"  {CAT_LABELS.get(cat, cat.title())}")
            cat_lbl.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #80c0ff;"
                " background: #1a2040; padding: 4px 8px;"
            )
            self._effects_layout.insertWidget(idx, cat_lbl)
            idx += 1

            for entry in cats[cat]:
                row_widget = self._make_effect_row(entry)
                self._effects_layout.insertWidget(idx, row_widget)
                idx += 1

        self._status_lbl.setText(
            f"✅ Loaded {len(entries)} DB entries for {self._game_serial}. "
            "Tick effects and choose values from the dropdowns, then click Install."
        )

    def _make_effect_row(self, entry: dict) -> QWidget:
        """Build a single effect row: checkbox + description + value picker.

        For entries with ``value_type`` = ``"int"`` or ``"float"`` the row also
        shows a custom text-input field so the user can type an arbitrary value
        (e.g. ``1000`` for money or ``90.0`` for FOV degrees).  A live hex
        preview label updates as they type so they can see exactly what PNACH
        code will be written.

        When an entry has an ``exclusion_group`` the row is visually tagged so
        the user understands only one option from that group can be active at a
        time (e.g. you can't stack "ki damage 2×" with "max ki damage").
        """
        from PyQt6.QtWidgets import QComboBox as QCBox
        from src.core.pnach_analyzer import (
            value_to_pnach_hex, INPUT_COMPAT_LABELS,
            SCE_PAD_BITMASK_DESCRIPTION, SCE_PAD_INCOMPATIBILITY_REASONS,
        )

        key = entry.get("key", "")
        # Parse address from key: CRC:PROC:ADDR
        parts = key.split(":")
        crc  = parts[0] if len(parts) > 0 else ""
        proc = parts[1] if len(parts) > 1 else "EE"
        addr = parts[2] if len(parts) > 2 else "00000000"

        desc             = entry.get("description", addr)
        value_map        = entry.get("value_map", {})
        value_type       = entry.get("value_type", "")   # "int" | "float" | "bool" | "button_combo" | ""
        excl_group       = entry.get("exclusion_group", "").strip()
        excl_note        = entry.get("exclusion_note", "").strip()
        input_compat     = entry.get("input_compat", "").strip()
        is_estimated     = entry.get("estimated", True)
        verification_status = entry.get("verification_status", "estimated")
        code_method      = entry.get("code_method", "static_write")
        patch_type       = entry.get("patch_type", "word")

        frame = QFrame()
        # Highlight frames that belong to an exclusion group with a subtle border
        border_color = "#3a2a60" if excl_group else "#2a2a50"
        frame.setStyleSheet(
            f"QFrame {{ background: #1a1a2e; border: 1px solid {border_color};"
            " border-radius: 4px; margin: 1px; }"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        # ── Checkbox ──────────────────────────────────────────────────
        chk = QCheckBox()
        chk.setToolTip("Enable this effect")
        row.addWidget(chk)

        # ── Description ───────────────────────────────────────────────
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #d0d0f0; min-width: 240px;")
        desc_lbl.setWordWrap(False)
        row.addWidget(desc_lbl, 1)

        # ── Verification-status badge ─────────────────────────────────
        _VS_BADGE: dict = {
            "verified":             ("✅", "#50c070", "#0a2a0a",
                                     "Verified — confirmed by hands-on PCSX2 testing"),
            "community_verified":   ("👥", "#50c070", "#0a2a0a",
                                     "Community verified — confirmed working by community reports"),
            "estimated":            ("🔬", "#b0a040", "#201800",
                                     "Estimated — research-derived address, not yet confirmed.\n"
                                     "Verify in PCSX2 Debug → Memory Search before relying on it."),
            "reported_not_working": ("❌", "#c04040", "#2a0a0a",
                                     "Known not working — reported to fail in at least one version."),
        }
        vs_icon, vs_fg, vs_bg, vs_tip = _VS_BADGE.get(
            verification_status, ("🔬", "#b0a040", "#201800", verification_status)
        )
        vs_badge = QLabel(vs_icon)
        vs_badge.setStyleSheet(
            f"color: {vs_fg}; background: {vs_bg}; border-radius: 3px;"
            " padding: 1px 4px; font-size: 11px;"
        )
        vs_badge.setToolTip(vs_tip)
        row.addWidget(vs_badge)

        # ── Code-method badge (only shown for non-static_write) ────────
        if code_method == "continuous_write":
            cm_badge = QLabel("⟳")
            cm_badge.setStyleSheet(
                "color: #e08030; background: #251500; border-radius: 3px;"
                " padding: 1px 4px; font-size: 11px;"
            )
            cm_badge.setToolTip(
                "Continuous write — the game resets this value every frame.\n"
                "A single pnach write may not persist; use a type-C (extended)\n"
                "cheat or re-apply this patch after each load."
            )
            row.addWidget(cm_badge)
        elif code_method == "conditional":
            cm_badge = QLabel("❓")
            cm_badge.setStyleSheet(
                "color: #7090e0; background: #0a1030; border-radius: 3px;"
                " padding: 1px 4px; font-size: 11px;"
            )
            cm_badge.setToolTip(
                "Conditional — this patch only applies when a game condition is met."
            )
            row.addWidget(cm_badge)
        elif code_method == "multi_address":
            cm_badge = QLabel("⊕")
            cm_badge.setStyleSheet(
                "color: #a060d0; background: #180a2a; border-radius: 3px;"
                " padding: 1px 4px; font-size: 11px;"
            )
            cm_badge.setToolTip(
                "Multi-address — this effect requires patching several memory locations."
            )
            row.addWidget(cm_badge)

        # ── Exclusion group tag (shown when entry is in a mutex group) ─
        if excl_group:
            # Show a small warning tag
            tag_tooltip = (
                excl_note
                or f"Only ONE option from group '{excl_group}' can be active "
                   "at a time. Enabling this will disable other effects in "
                   "the same group."
            )
            excl_tag = QLabel("⚠ excl")
            excl_tag.setStyleSheet(
                "color: #e0a030; font-size: 10px; font-style: italic;"
                " background: #2a1a10; border-radius: 3px; padding: 1px 4px;"
            )
            excl_tag.setToolTip(tag_tooltip)
            row.addWidget(excl_tag)

        # ── Input compatibility badge (shown for button_combo entries) ─
        # Badge appearance keyed by input_compat value.
        _COMPAT_BADGE: dict = {
            "standard_sce_pad":  ("✅ SCE pad",
                                   "color: #40c060; font-size: 10px;"
                                   " background: #0a2a0a; border-radius: 3px; padding: 1px 4px;",
                                   True),   # True = use SCE_PAD_BITMASK_DESCRIPTION in tip
            "inverted_sce_pad":  ("⚠ non-std",
                                   "color: #e0a030; font-size: 10px;"
                                   " background: #2a1a00; border-radius: 3px; padding: 1px 4px;",
                                   False),
            "custom_polling":    ("⚠ non-std",
                                   "color: #e0a030; font-size: 10px;"
                                   " background: #2a1a00; border-radius: 3px; padding: 1px 4px;",
                                   False),
            "analog_only":       ("❌ analog",
                                   "color: #c04040; font-size: 10px;"
                                   " background: #2a0a0a; border-radius: 3px; padding: 1px 4px;",
                                   False),
        }
        if value_type == "button_combo" and input_compat:
            badge_text, badge_style, use_bitmask_tip = _COMPAT_BADGE.get(
                input_compat,
                ("⚠ unverified",
                 "color: #909090; font-size: 10px;"
                 " background: #1a1a1a; border-radius: 3px; padding: 1px 4px;",
                 False),
            )
            detail_text = (SCE_PAD_BITMASK_DESCRIPTION
                           if use_bitmask_tip else SCE_PAD_INCOMPATIBILITY_REASONS)
            badge_tip = (
                INPUT_COMPAT_LABELS.get(input_compat, input_compat) + "\n\n"
                + detail_text
            )
            compat_badge = QLabel(badge_text)
            compat_badge.setStyleSheet(badge_style)
            compat_badge.setToolTip(badge_tip)
            row.addWidget(compat_badge)

        # ── Address badge ─────────────────────────────────────────────
        addr_lbl = QLabel(f"[{proc}:{addr}]")
        addr_lbl.setStyleSheet("color: #505080; font-family: monospace; font-size: 11px;")
        row.addWidget(addr_lbl)

        # ── Value dropdown (shown when value_map is available) ────────
        value_combo = None
        if value_map:
            # Choose context-sensitive header label
            if value_type == "button_combo":
                val_header = QLabel("Combo:")
            elif value_type == "button":
                # Legacy single-button type (all entries upgraded to button_combo in wave 9;
                # kept for backward-compatibility with user-edited DB snapshots).
                val_header = QLabel("Button:")
            else:
                val_header = QLabel("Value:")
            val_header.setStyleSheet("color: #7090c0; font-size: 11px;")
            row.addWidget(val_header)

            value_combo = QCBox()
            if value_type == "button_combo":
                value_combo.setMinimumWidth(280)
                compat_label = INPUT_COMPAT_LABELS.get(input_compat, "")
                value_combo.setToolTip(
                    "Select the PS2 button combination that toggles freecam mode.\n"
                    "You must press ALL listed buttons simultaneously to toggle.\n\n"
                    "When freecam is active:\n"
                    "  • Left stick — pan camera\n"
                    "  • Right stick — rotate / tilt\n"
                    "  • Circle (○) — move forward\n"
                    "  • Square (□) — move backward\n"
                    "  • Cross (✕) — descend\n"
                    "  • Triangle (△) — ascend\n\n"
                    + (f"SCE Pad Compatibility:  {compat_label}\n\n" if compat_label else "")
                    + SCE_PAD_BITMASK_DESCRIPTION + "\n\n"
                    "⚠ Addresses are research-estimated — verify in PCSX2 debugger."
                )
            elif value_type == "button":
                value_combo.setMinimumWidth(240)
                value_combo.setToolTip(
                    "Select the PS2 controller button that will activate this feature.\n"
                    "Left stick pans camera, right stick rotates, Cross (X) descends, "
                    "Triangle ascends."
                )
            else:
                value_combo.setMinimumWidth(200)
                value_combo.setToolTip(
                    "Select a value for this effect.\n"
                    "Options are labeled by what they do (e.g. 'double height', 'normal speed')."
                )
            default_first = sorted(value_map.items(), key=lambda kv: (
                0 if "default" in kv[1].lower() or "1×" in kv[1] or "4:3" in kv[1] else 1,
                kv[1],
            ))
            for hex_val, label in default_first:
                value_combo.addItem(label, hex_val)
            row.addWidget(value_combo)
        else:
            placeholder = QLabel("(no options)")
            placeholder.setStyleSheet("color: #505060; font-size: 11px; font-style: italic;")
            row.addWidget(placeholder)

        # ── Custom value input (int / float entries only) ─────────────
        custom_edit  = None
        custom_label = None   # live hex preview

        if value_type in ("int", "float"):
            sep = QLabel("or")
            sep.setStyleSheet("color: #6060a0; font-size: 11px;")
            row.addWidget(sep)

            custom_edit = QLineEdit()
            custom_edit.setMaximumWidth(110)
            custom_edit.setClearButtonEnabled(True)
            if value_type == "int":
                custom_edit.setPlaceholderText("e.g. 1000")
                custom_edit.setToolTip(
                    "Type any whole number (e.g. 1000 or 1,000,000).\n"
                    "The application will convert it to the correct PNACH code."
                )
            else:
                custom_edit.setPlaceholderText("e.g. 2.5")
                custom_edit.setToolTip(
                    "Type any decimal number (e.g. 2.5 for 2.5× speed, "
                    "or 90.0 for 90° FOV).\n"
                    "The application will convert it to IEEE 754 hex for you."
                )

            # Live hex preview label
            custom_label = QLabel("")
            custom_label.setStyleSheet(
                "color: #50d090; font-family: monospace; font-size: 11px; min-width: 80px;"
            )
            custom_label.setToolTip("PNACH hex that will be written")

            def _on_custom_changed(text, vtype=value_type,
                                   label_widget=custom_label, combo_widget=value_combo):
                """Update the live hex preview and dim the combo when custom is active."""
                text = text.strip()
                if not text:
                    label_widget.setText("")
                    if combo_widget:
                        combo_widget.setEnabled(True)
                    return
                hx, err = value_to_pnach_hex(text, vtype)
                if hx:
                    label_widget.setText(f"→ {hx}")
                    label_widget.setStyleSheet(
                        "color: #50d090; font-family: monospace; font-size: 11px;"
                    )
                    if combo_widget:
                        combo_widget.setEnabled(False)   # custom overrides preset
                else:
                    label_widget.setText(err or "?")
                    label_widget.setStyleSheet(
                        "color: #e05050; font-family: monospace; font-size: 11px;"
                    )
                    if combo_widget:
                        combo_widget.setEnabled(True)

            custom_edit.textChanged.connect(_on_custom_changed)
            row.addWidget(custom_edit)
            row.addWidget(custom_label)

        # ── Store all references ──────────────────────────────────────
        self._patch_widgets.append({
            "check":                chk,
            "value_combo":          value_combo,
            "custom_edit":          custom_edit,
            "value_type":           value_type,
            "crc":                  crc,
            "proc":                 proc,
            "addr":                 addr,
            "description":          desc,
            "value_map":            value_map,
            "exclusion_group":      excl_group,
            "exclusion_note":       excl_note,
            "patch_type":           patch_type,
            "verification_status":  verification_status,
            "code_method":          code_method,
        })

        return frame

    # ------------------------------------------------------------------
    # Generate PNACH content
    # ------------------------------------------------------------------

    def _collect_selected_patches(self) -> tuple:
        """Return (patches: list[dict], conflicts: list[str]).

        Value resolution priority:
        1. If the user typed a custom value in the free-text field (and it
           parses without error), use that.
        2. Otherwise use the selected option in the dropdown.
        3. Fall back to ``00000000``.

        Conflicts include:
        * Address conflicts: two selected entries write to the same address.
        * Exclusion-group conflicts: two selected entries share the same
          ``exclusion_group`` value, meaning they are mutually exclusive (e.g.
          a 2× damage multiplier and a max-damage cheat both target the same
          game variable).  The user must disable one before installing.

        Note: an entry with a ki-blast *visual* size modifier deliberately has
        NO exclusion_group, so it is always safe to combine with ki-damage
        multipliers (they control different things).
        """
        from src.core.pnach_analyzer import value_to_pnach_hex, check_exclusion_conflicts

        selected = []
        addr_seen: dict = {}
        conflicts = []
        selected_for_excl: list = []

        for pw in self._patch_widgets:
            if not pw["check"].isChecked():
                continue

            # ── Resolve hex value ──────────────────────────────────────
            hex_val = "00000000"
            vtype = pw.get("value_type", "")

            # 1. Custom free-text field (int / float entries)
            custom_edit = pw.get("custom_edit")
            if custom_edit is not None:
                raw = custom_edit.text().strip()
                if raw and vtype in ("int", "float"):
                    hx, err = value_to_pnach_hex(raw, vtype)
                    if hx:
                        hex_val = hx
                    else:
                        # Invalid custom input — fall through to dropdown
                        pass

            # 2. Dropdown option (used when custom is empty or invalid)
            if hex_val == "00000000":
                value_combo = pw.get("value_combo")
                if value_combo is not None and value_combo.isEnabled():
                    hex_val = value_combo.currentData() or "00000000"
                elif pw.get("value_map"):
                    hex_val = list(pw["value_map"].keys())[0]

            # ── Address conflict detection ─────────────────────────────
            addr_key = f"{pw['proc']}:{pw['addr']}"
            if addr_key in addr_seen:
                conflicts.append(
                    f"Address {pw['addr']} ({pw['description']!r}) conflicts with "
                    f"{addr_seen[addr_key]!r}"
                )
            else:
                addr_seen[addr_key] = pw["description"]

            selected.append({
                "processor":           pw["proc"],
                "address":             pw["addr"],
                "value":               hex_val,
                "description":         pw["description"],
                "patch_type":          pw.get("patch_type", "word"),
                "verification_status": pw.get("verification_status", "estimated"),
                "code_method":         pw.get("code_method", "static_write"),
                "crc":                 pw["crc"],
                "exclusion_group":     pw.get("exclusion_group", ""),
                "exclusion_note":      pw.get("exclusion_note", ""),
            })
            selected_for_excl.append({
                "description":     pw["description"],
                "exclusion_group": pw.get("exclusion_group", ""),
                "exclusion_note":  pw.get("exclusion_note", ""),
            })

        # ── Exclusion-group conflict detection ─────────────────────────
        excl_conflicts = check_exclusion_conflicts(selected_for_excl)
        for ec in excl_conflicts:
            conflicts.append(ec["message"])

        return selected, conflicts

    def _get_pnach_text(self) -> str | None:
        from src.core.pnach_analyzer import generate_pnach_text, entries_for_serial

        patches, conflicts = self._collect_selected_patches()
        if not patches:
            QMessageBox.information(self, "Nothing selected",
                                    "Tick at least one effect to generate a PNACH patch.")
            return None

        if conflicts:
            msg = "⚠ Conflicts detected:\n\n" + "\n".join(f"• {c}" for c in conflicts)
            msg += "\n\nOnly the first selected value for each address will be used."
            QMessageBox.warning(self, "Address Conflicts", msg)
            # De-duplicate by address (keep first)
            seen = set()
            deduped = []
            for p in patches:
                k = f"{p['processor']}:{p['address']}"
                if k not in seen:
                    seen.add(k)
                    deduped.append(p)
            patches = deduped

        # Get CRC from first patch
        game_crc = patches[0].get("crc", "00000000") if patches else "00000000"
        # Get game title from serial
        from src.core.game_registry import lookup_game_title
        game_title = lookup_game_title(self._game_serial) or self._game_serial

        return generate_pnach_text(game_crc, game_title, patches), game_crc

    def _preview_pnach(self):
        result = self._get_pnach_text()
        if result is None:
            return
        text, crc = result
        dlg = QDialog(self)
        dlg.setWindowTitle(f"PNACH Preview — {crc}.pnach")
        dlg.resize(640, 480)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setPlainText(text)
        te.setReadOnly(True)
        te.setFontFamily("Courier New")
        layout.addWidget(te)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()

    def _install_pnach(self):
        result = self._get_pnach_text()
        if result is None:
            return
        text, crc = result

        cheats_dir = self._dir_edit.text().strip()
        if not cheats_dir:
            QMessageBox.warning(self, "No Cheats Folder",
                                "Please specify your PCSX2 cheats/ folder path.")
            return

        import os
        os.makedirs(cheats_dir, exist_ok=True)
        dest = os.path.join(cheats_dir, f"{crc}.pnach")

        # Smart conflict detection when file already exists
        if os.path.exists(dest):
            try:
                from src.core.pnach import parse_pnach, PnachFile, PatchLine

                existing = parse_pnach(dest)
                # Parse new patches from the text we're about to write
                new_file = PnachFile(game_crc=crc)
                for raw in text.splitlines():
                    line = raw.strip()
                    if not line or line.startswith("//"):
                        continue
                    low = line.lower()
                    if low.startswith("gametitle="):
                        new_file.game_title = line.split("=", 1)[1].strip()
                        continue
                    if low.startswith("comment="):
                        new_file.comment = line.split("=", 1)[1].strip()
                        continue
                    import re as _re
                    m = _re.match(
                        r"^\s*patch\s*=\s*(\d+)\s*,\s*(\w+)\s*,\s*([0-9A-Fa-f]+)\s*,"
                        r"\s*(\w+)\s*,\s*([0-9A-Fa-f]+)",
                        line, _re.IGNORECASE,
                    )
                    if m:
                        new_file.patches.append(PatchLine(
                            enabled=int(m.group(1)),
                            processor=m.group(2).upper(),
                            address=m.group(3).upper().zfill(8),
                            size=m.group(4).lower(),
                            value=m.group(5).upper(),
                        ))

                # Find overlapping addresses
                existing_keys = {p.dedup_key for p in existing.patches}
                new_keys = {p.dedup_key for p in new_file.patches}
                overlapping = existing_keys & new_keys

                if overlapping:
                    # Build a readable summary of conflicts
                    overlap_lines = []
                    for pk in sorted(overlapping):
                        ex_patch = next(
                            (p for p in existing.patches if p.dedup_key == pk), None
                        )
                        nw_patch = next(
                            (p for p in new_file.patches if p.dedup_key == pk), None
                        )
                        if ex_patch and nw_patch:
                            overlap_lines.append(
                                f"  {pk[0]}:{pk[1]}  "
                                f"existing={ex_patch.value}  new={nw_patch.value}"
                            )

                    conflict_summary = "\n".join(overlap_lines[:10])
                    if len(overlap_lines) > 10:
                        conflict_summary += f"\n  … and {len(overlap_lines) - 10} more"

                    from PyQt6.QtWidgets import QDialogButtonBox
                    msg = QMessageBox(self)
                    msg.setWindowTitle("PNACH Conflict Detected")
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setText(
                        f"<b>{crc}.pnach</b> already exists and shares "
                        f"<b>{len(overlapping)}</b> address(es) with the new patches:"
                    )
                    msg.setInformativeText(
                        f"<pre>{conflict_summary}</pre>\n\n"
                        "• <b>Merge</b>: keep existing patches, add new ones "
                        "(new values win on address conflicts)\n"
                        "• <b>Overwrite</b>: replace the file entirely with new patches\n"
                        "• <b>Cancel</b>: abort"
                    )
                    merge_btn = msg.addButton("Merge", QMessageBox.ButtonRole.AcceptRole)
                    over_btn = msg.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
                    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                    msg.exec()
                    clicked = msg.clickedButton()
                    if clicked is None or clicked.text() == "Cancel":
                        return
                    if clicked is merge_btn:
                        # Merge: start with existing, new patches override on conflict
                        merged_map: dict[tuple, object] = {p.dedup_key: p for p in existing.patches}
                        for p in new_file.patches:
                            merged_map[p.dedup_key] = p
                        existing.patches = list(merged_map.values())
                        text = existing.to_text()
                    # else overwrite — use text as-is
                else:
                    # No overlapping addresses — ask user: merge or overwrite
                    reply = QMessageBox.question(
                        self, "File Exists",
                        f"{crc}.pnach already exists ({len(existing.patches)} existing patch lines,\n"
                        f"{len(new_file.patches)} new — no address conflicts).\n\n"
                        "Merge new patches into the existing file, or overwrite?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        | QMessageBox.StandardButton.Cancel,
                    )
                    if reply == QMessageBox.StandardButton.Cancel:
                        return
                    if reply == QMessageBox.StandardButton.Yes:
                        # Merge: append new patches that aren't already present
                        existing_keys2 = {p.dedup_key for p in existing.patches}
                        for p in new_file.patches:
                            if p.dedup_key not in existing_keys2:
                                existing.patches.append(p)
                        text = existing.to_text()
                    # else: overwrite — use text as-is

            except Exception:
                # If parsing fails, fall back to simple overwrite prompt
                reply = QMessageBox.question(
                    self, "File Exists",
                    f"{crc}.pnach already exists.\nOverwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(
                self, "✅ Installed",
                f"PNACH written to:\n{dest}\n\n"
                "Launch PCSX2 and the patch will be applied automatically.\n\n"
                "💡 Make sure 'Enable Cheats' is checked in PCSX2 → Game Properties."
            )
        except OSError as exc:
            QMessageBox.critical(self, "Write Error", f"Could not write PNACH:\n{exc}")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select PCSX2 cheats/ folder",
                                              self._dir_edit.text())
        if d:
            self._dir_edit.setText(d)



# ---------------------------------------------------------------------------
# CustomCardDialog — create a catalogue card for a pre-existing mod
# ---------------------------------------------------------------------------

class CustomCardDialog(QDialog):
    """Form dialog for creating a custom catalogue entry (card) for a
    pre-existing mod that is not in the built-in catalogue.

    After the user fills in the form and accepts, the entry is written to the
    ``user_catalogue/my_cards.json`` file next to the application executable.
    The entry then appears in the Browse panel after a catalogue reload.

    Parameters
    ----------
    parent:
        Parent widget.
    prefill:
        Optional dict of field values to pre-populate the form.  Useful when
        opening this dialog from :class:`InstalledScannerDialog` with data
        auto-detected from a scanned item.
    """

    #: Emitted with the newly created entry dict when the user accepts.
    card_created = pyqtSignal(dict)

    def __init__(self, parent=None, *, prefill: dict = None):
        super().__init__(parent)
        self._prefill = prefill or {}
        self.setWindowTitle("✏  Create Custom Catalogue Card")
        self.setMinimumWidth(560)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        hdr = QLabel(
            "Fill in the details below to add this mod to your personal catalogue.\n"
            "Fields marked * are required."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.setSpacing(6)
        row = 0

        def _add_row(label_text, widget, hint=""):
            nonlocal row
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form.addWidget(lbl, row, 0)
            form.addWidget(widget, row, 1)
            if hint:
                hint_lbl = QLabel(f"<small><i>{hint}</i></small>")
                hint_lbl.setWordWrap(True)
                row += 1
                form.addWidget(hint_lbl, row, 1)
            row += 1

        # Type *
        self._type_combo = QComboBox()
        for val, lbl in [
            ("texture_pack", "Texture Pack"),
            ("pnach",        "PNACH Patch"),
            ("save_file",    "Memory Card Save"),
            ("cheat",        "Widescreen / Cheat Patch"),
            ("cover_art",    "Cover Art"),
        ]:
            self._type_combo.addItem(lbl, val)
        prefill_type = self._prefill.get("type", "")
        if hasattr(prefill_type, "value"):
            prefill_type = prefill_type.value
        for i in range(self._type_combo.count()):
            if self._type_combo.itemData(i) == prefill_type:
                self._type_combo.setCurrentIndex(i)
                break
        _add_row("Type *:", self._type_combo)

        # Name *
        self._name_edit = QLineEdit(self._prefill.get("name", ""))
        self._name_edit.setPlaceholderText("e.g. Sly 2 HD Textures")
        _add_row("Name *:", self._name_edit)

        # Game *
        self._game_edit = QLineEdit(self._prefill.get("game", ""))
        self._game_edit.setPlaceholderText("e.g. Sly 2: Band of Thieves")
        _add_row("Game *:", self._game_edit)

        # Serial *
        self._serial_edit = QLineEdit(self._prefill.get("game_serial", ""))
        self._serial_edit.setPlaceholderText("e.g. SCUS-97264")
        _add_row("Serial *:", self._serial_edit, hint="PS2 disc serial (XX(X)-NNNNN)")

        # Author
        self._author_edit = QLineEdit(self._prefill.get("author", ""))
        self._author_edit.setPlaceholderText("e.g. YourName")
        _add_row("Author:", self._author_edit)

        # URL
        self._url_edit = QLineEdit(self._prefill.get("url", ""))
        self._url_edit.setPlaceholderText("https://…  (leave blank for personal packs)")
        _add_row("URL:", self._url_edit)

        # Description
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("Short description shown in the catalogue card")
        self._desc_edit.setPlainText(self._prefill.get("description", ""))
        self._desc_edit.setFixedHeight(64)
        _add_row("Description:", self._desc_edit)

        # Source
        self._source_edit = QLineEdit(self._prefill.get("source", "Personal"))
        self._source_edit.setPlaceholderText("e.g. Personal, GameFront, GBAtemp")
        _add_row("Source:", self._source_edit)

        # Size label
        self._size_edit = QLineEdit(self._prefill.get("size_label", ""))
        self._size_edit.setPlaceholderText("e.g. ~250 MB  (auto-detected if path set)")
        _add_row("Size:", self._size_edit)

        layout.addLayout(form)

        # Status label (errors shown here)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #e74c3c;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("💾 Save Card")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    def _on_accept(self):
        from src.core.custom_card_builder import build_entry, save_entry, VALID_MOD_TYPES

        mod_type    = self._type_combo.currentData() or "texture_pack"
        name        = self._name_edit.text().strip()
        game        = self._game_edit.text().strip()
        serial      = self._serial_edit.text().strip().upper()
        author      = self._author_edit.text().strip()
        url         = self._url_edit.text().strip()
        description = self._desc_edit.toPlainText().strip()
        source      = self._source_edit.text().strip() or "Personal"
        size_label  = self._size_edit.text().strip()

        # Validate
        errors = []
        if not name:
            errors.append("• Name is required.")
        if not game:
            errors.append("• Game is required.")
        if not serial:
            errors.append("• Serial is required.")

        if errors:
            self._status.setText("\n".join(errors))
            return

        try:
            entry = build_entry(
                mod_type=mod_type,
                name=name,
                game=game,
                game_serial=serial,
                author=author,
                url=url,
                description=description,
                source=source,
                size_label=size_label,
            )
        except ValueError as exc:
            self._status.setText(str(exc))
            return

        try:
            out_path = save_entry(entry)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save card:\n{exc}")
            return

        QMessageBox.information(
            self, "✅ Card Saved",
            f"Your custom catalogue card has been saved to:\n{out_path}\n\n"
            "Use the 🔄 Reload button in the Browse panel to see it."
        )
        self.card_created.emit(entry)
        self.accept()


# ---------------------------------------------------------------------------
# InstalledScannerDialog — detect pre-existing PCSX2 content
# ---------------------------------------------------------------------------

class InstalledScannerDialog(QDialog):
    """Scans the PCSX2 directory for content that was installed outside of the
    PS2 Mod Manager so it can be registered and managed.

    The scanner checks for:

    * Texture packs (``textures/<SERIAL>/replacements/``)
    * PNACH patches (``cheats/*.pnach``)
    * Widescreen / cheat patches (``cheats_ws/*.pnach``)
    * Cover art images (``covers/<SERIAL>.png``)

    For each found item the dialog suggests matching catalogue entries (if any)
    or offers to open the :class:`CustomCardDialog` to create a new one.

    Parameters
    ----------
    config:
        Current :class:`~src.models.mod.AppConfig` instance (provides PCSX2
        paths and any ``managed_paths`` info).
    parent:
        Parent widget.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._items = []          # list[UnmanagedItem]
        self._catalogue = []      # full catalogue for matching
        self.setWindowTitle("🔍  Scan for Unmanaged PCSX2 Content")
        self.setMinimumSize(820, 560)
        self._build_ui()
        self._run_scan()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "PS2 Mod Manager has scanned your PCSX2 folder for content that was\n"
            "installed outside of the manager.  Select an item to see suggested\n"
            "catalogue matches, or create a custom card for it."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        # Splitter: item list (left) + detail panel (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: list of found items ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_item_selected)
        left_layout.addWidget(self._list_widget)

        # Re-scan button
        rescan_btn = QPushButton("🔄 Re-scan")
        rescan_btn.clicked.connect(self._run_scan)
        left_layout.addWidget(rescan_btn)

        splitter.addWidget(left)

        # --- Right: detail + match panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QLabel("← Select an item from the list")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(self._detail_label)

        match_lbl = QLabel("Suggested catalogue matches:")
        right_layout.addWidget(match_lbl)

        self._match_list = QListWidget()
        self._match_list.setAlternatingRowColors(True)
        right_layout.addWidget(self._match_list)

        action_row = QHBoxLayout()

        self._create_btn = QPushButton("✏  Create Custom Card")
        self._create_btn.setToolTip(
            "Open the card creator to add this item to your personal catalogue"
        )
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._on_create_card)
        action_row.addWidget(self._create_btn)

        action_row.addStretch()

        right_layout.addLayout(action_row)
        splitter.addWidget(right)
        splitter.setSizes([300, 500])
        layout.addWidget(splitter, 1)

        # Close button
        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    # ------------------------------------------------------------------
    def _run_scan(self):
        self._list_widget.clear()
        self._match_list.clear()
        self._detail_label.setText("⏳ Scanning…")
        QApplication.processEvents()

        try:
            from src.core.installed_scanner import scan_all, find_catalogue_matches
            from src.core.catalogue_loader import CATALOGUE
        except Exception as exc:
            self._detail_label.setText(f"Scan failed: {exc}")
            return

        self._catalogue = CATALOGUE
        self._items = scan_all(self._config)

        if not self._items:
            self._detail_label.setText(
                "✅ No unmanaged content found.\n\n"
                "All PCSX2 texture packs, PNACH files, and cover art images "
                "appear to be managed by PS2 Mod Manager (or the relevant "
                "PCSX2 directories are empty / not configured)."
            )
            return

        for item in self._items:
            label = f"[{item.type_label}]  {item.name}"
            if item.suggested_game:
                label += f"  –  {item.suggested_game}"
            elif item.serial:
                label += f"  –  {item.serial}"
            list_item = QListWidgetItem(label)
            self._list_widget.addItem(list_item)

        self._detail_label.setText(
            f"Found {len(self._items)} unmanaged item(s).  "
            "Select one to see suggested matches."
        )
        self._create_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_item_selected(self, row: int):
        if row < 0 or row >= len(self._items):
            return

        from src.core.installed_scanner import find_catalogue_matches

        item = self._items[row]
        self._create_btn.setEnabled(True)

        # Detail text
        lines = [
            f"<b>{item.name}</b>",
            f"Type: {item.type_label}",
        ]
        if item.serial:
            lines.append(f"Serial: {item.serial}")
        if item.suggested_game:
            lines.append(f"Game: {item.suggested_game}")
        if item.crc:
            lines.append(f"CRC: {item.crc}")
        lines.append(f"Size: {item.size_label}  |  Files: {item.file_count}")
        lines.append(f"Path: <small>{item.path}</small>")
        self._detail_label.setText("<br>".join(lines))

        # Catalogue matches
        self._match_list.clear()
        matches = find_catalogue_matches(item, self._catalogue, limit=8)
        if matches:
            for m in matches:
                mtext = (
                    f"{m.get('name', '')}  –  {m.get('game', '')}  "
                    f"[{m.get('author', '')}]"
                )
                self._match_list.addItem(mtext)
        else:
            self._match_list.addItem("(no catalogue matches found — create a custom card)")

    # ------------------------------------------------------------------
    def _on_create_card(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]

        prefill = {
            "type":        item.item_type,
            "name":        item.name,
            "game":        item.suggested_game,
            "game_serial": item.serial,
            "size_label":  item.size_label,
        }

        dlg = CustomCardDialog(self, prefill=prefill)
        dlg.exec()


# ---------------------------------------------------------------------------
# ConflictResolverDialog — detect and resolve conflicts between installed content
# ---------------------------------------------------------------------------

class ConflictResolverDialog(QDialog):
    """Scans installed PCSX2 content for conflicts — situations where two or
    more items would interfere with each other at runtime.

    Detected conflict types include:

    * Duplicate CRC ``.pnach`` files in both ``cheats/`` and ``cheats_ws/``
    * Two ``.pnach`` files patching the **same EE memory address** for the same CRC
    * Multiple cover-art images for the same PS2 serial
    * Multiple texture sub-packs merged into one replacements folder

    Each conflict shows its severity (❌ Error / ⚠️ Warning / ℹ️ Info), a
    detailed description, and a suggested resolution.  Where safe, an
    **Auto-fix** button removes redundant files automatically.

    Parameters
    ----------
    config:
        Current :class:`~src.models.mod.AppConfig` instance providing PCSX2 paths.
    parent:
        Parent widget.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config    = config
        self._conflicts = []       # list[Conflict]
        self.setWindowTitle("⚠  Conflict Resolver")
        self.setMinimumSize(860, 560)
        self._build_ui()
        self._run_scan()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "PS2 Mod Manager has scanned your installed content for conflicts.\n"
            "Select a conflict from the list on the left to see details and\n"
            "suggested resolutions on the right."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        # Splitter: conflict list (left) + detail panel (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: list of conflicts ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        left_layout.addWidget(self._summary_label)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_conflict_selected)
        left_layout.addWidget(self._list_widget)

        rescan_btn = QPushButton("🔄 Re-scan")
        rescan_btn.clicked.connect(self._run_scan)
        left_layout.addWidget(rescan_btn)

        splitter.addWidget(left)

        # --- Right: detail panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QLabel("← Select a conflict from the list")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_label.setTextFormat(Qt.TextFormat.RichText)
        right_layout.addWidget(self._detail_label, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep)

        # Resolution row
        res_lbl = QLabel("<b>Suggested Resolution:</b>")
        right_layout.addWidget(res_lbl)

        self._resolution_label = QLabel("")
        self._resolution_label.setWordWrap(True)
        right_layout.addWidget(self._resolution_label)

        # Files involved
        files_lbl = QLabel("<b>Files involved:</b>")
        right_layout.addWidget(files_lbl)

        self._files_list = QListWidget()
        self._files_list.setMaximumHeight(110)
        self._files_list.setAlternatingRowColors(True)
        right_layout.addWidget(self._files_list)

        # Action buttons
        action_row = QHBoxLayout()

        self._autofix_btn = QPushButton("🔧 Auto-Fix")
        self._autofix_btn.setToolTip("Automatically resolve this conflict (where safe)")
        self._autofix_btn.setEnabled(False)
        self._autofix_btn.clicked.connect(self._on_auto_fix)
        action_row.addWidget(self._autofix_btn)

        open_folder_btn = QPushButton("📂 Open Folder")
        open_folder_btn.setToolTip("Open the folder containing the conflicting file(s)")
        open_folder_btn.clicked.connect(self._on_open_folder)
        action_row.addWidget(open_folder_btn)

        action_row.addStretch()
        right_layout.addLayout(action_row)

        splitter.addWidget(right)
        splitter.setSizes([280, 560])
        layout.addWidget(splitter, 1)

        # Close button
        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    # ------------------------------------------------------------------
    def _run_scan(self):
        self._list_widget.clear()
        self._detail_label.setText("⏳ Scanning for conflicts…")
        self._resolution_label.setText("")
        self._files_list.clear()
        self._autofix_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            from src.core.conflict_resolver import resolve_all_conflicts
        except Exception as exc:
            self._detail_label.setText(f"Scan failed: {exc}")
            return

        self._conflicts = resolve_all_conflicts(self._config)

        if not self._conflicts:
            self._summary_label.setText("✅ No conflicts found!")
            self._detail_label.setText(
                "✅ No conflicts detected.\n\n"
                "All installed content appears consistent.  PNACH files, "
                "texture packs, and cover art images are not conflicting with "
                "each other."
            )
            return

        errors   = sum(1 for c in self._conflicts if c.severity == "error")
        warnings = sum(1 for c in self._conflicts if c.severity == "warning")
        infos    = sum(1 for c in self._conflicts if c.severity == "info")

        parts = []
        if errors:
            parts.append(f"{errors} error(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")
        if infos:
            parts.append(f"{infos} info")
        self._summary_label.setText(f"Found: {', '.join(parts)}")

        for conflict in self._conflicts:
            label = f"{conflict.severity_label}  {conflict.title}"
            item = QListWidgetItem(label)
            item.setForeground(
                __import__('PyQt6.QtGui', fromlist=['QColor']).QColor(conflict.severity_color)
            )
            self._list_widget.addItem(item)

        self._detail_label.setText(
            f"Found <b>{len(self._conflicts)}</b> conflict(s).  "
            "Select one for details."
        )

    # ------------------------------------------------------------------
    def _on_conflict_selected(self, row: int):
        if row < 0 or row >= len(self._conflicts):
            return

        conflict = self._conflicts[row]

        color = conflict.severity_color
        detail_html = (
            f"<b style='color:{color}'>{conflict.severity_label}</b><br>"
            f"<b>{conflict.title}</b><br><br>"
            f"{conflict.description.replace(chr(10), '<br>')}"
        )
        self._detail_label.setText(detail_html)
        self._resolution_label.setText(conflict.resolution)

        self._files_list.clear()
        for path in conflict.items:
            self._files_list.addItem(str(path))

        self._autofix_btn.setEnabled(conflict.can_auto_fix)

    # ------------------------------------------------------------------
    def _on_auto_fix(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._conflicts):
            return

        conflict = self._conflicts[row]
        reply = QMessageBox.question(
            self,
            "Auto-Fix Conflict",
            f"This will:\n{conflict.resolution}\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from src.core.conflict_resolver import auto_fix_conflict
            ok, message = auto_fix_conflict(conflict)
        except Exception as exc:
            QMessageBox.critical(self, "Auto-Fix Error", str(exc))
            return

        if ok:
            QMessageBox.information(self, "✅ Fixed", message)
            self._run_scan()
        else:
            QMessageBox.warning(self, "Auto-Fix Failed", message)

    # ------------------------------------------------------------------
    def _on_open_folder(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._conflicts):
            return

        conflict = self._conflicts[row]
        if not conflict.items:
            return

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        folder = conflict.items[0]
        if folder.is_file():
            folder = folder.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


# ---------------------------------------------------------------------------
# BackupManagerDialog
# ---------------------------------------------------------------------------

class BackupManagerDialog(QDialog):
    """Create, browse, restore and delete backups of PCSX2 managed content.

    Backups are timestamped ZIP archives stored in a ``backups/`` folder next
    to the application executable.  Each archive may contain one or more of:

    * PNACH cheat files (``cheats/``)
    * Widescreen PNACH patches (``cheats_ws/``)
    * Cover-art images (``covers/``)
    * Texture-pack directories (``textures/``)

    Parameters
    ----------
    config:
        Current :class:`~src.models.mod.AppConfig` instance providing PCSX2 paths.
    parent:
        Parent widget.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config  = config
        self._entries = []   # list[BackupEntry]
        self.setWindowTitle("💾  Backup Manager")
        self.setMinimumSize(780, 480)
        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "Backups are ZIP archives of your PCSX2 data (PNACH files, cover art, "
            "texture packs).\nSelect an archive to view details or restore it."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: backup list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._list_widget)

        create_row = QHBoxLayout()
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("Optional note…")
        self._note_edit.setMaxLength(40)
        create_row.addWidget(self._note_edit, 1)

        create_btn = QPushButton("➕ Create Backup")
        create_btn.setObjectName("primary_btn")
        create_btn.setToolTip("Create a new backup archive now")
        create_btn.clicked.connect(self._on_create)
        create_row.addWidget(create_btn)

        left_layout.addLayout(create_row)
        splitter.addWidget(left)

        # --- Right: detail panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QLabel("← Select a backup from the list")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_label.setTextFormat(Qt.TextFormat.RichText)
        right_layout.addWidget(self._detail_label, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep)

        action_row = QHBoxLayout()

        self._restore_btn = QPushButton("♻  Restore")
        self._restore_btn.setToolTip(
            "Extract this backup into the PCSX2 directories (overwrites existing files)"
        )
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._on_restore)
        action_row.addWidget(self._restore_btn)

        self._delete_btn = QPushButton("🗑  Delete")
        self._delete_btn.setToolTip("Permanently delete this backup archive")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        action_row.addWidget(self._delete_btn)

        action_row.addStretch()

        open_dir_btn = QPushButton("📂 Open Backups Folder")
        open_dir_btn.setToolTip("Open the backups folder in the file manager")
        open_dir_btn.clicked.connect(self._on_open_dir)
        action_row.addWidget(open_dir_btn)

        right_layout.addLayout(action_row)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ------------------------------------------------------------------
    def _refresh_list(self):
        self._list_widget.clear()
        try:
            from src.core.backup_manager import list_backups
            self._entries = list_backups(self._config)
        except Exception as exc:
            self._entries = []
            self._detail_label.setText(f"<i>Could not read backups: {exc}</i>")
            return

        for entry in self._entries:
            self._list_widget.addItem(f"{entry.label}  ({entry.size_label})")

        if not self._entries:
            self._detail_label.setText("<i>No backups found.  Use ➕ Create Backup to make one.</i>")

        self._restore_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._entries):
            self._detail_label.setText("← Select a backup from the list")
            self._restore_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            return

        entry = self._entries[row]
        html = (
            f"<b>{entry.label}</b><br>"
            f"<br>"
            f"<b>Created:</b> {entry.created_at}<br>"
            f"<b>Size (uncompressed):</b> {entry.size_label}<br>"
        )
        if entry.note:
            html += f"<b>Note:</b> {entry.note}<br>"
        html += f"<br><b>Archive path:</b><br><code>{entry.path}</code>"
        self._detail_label.setText(html)
        self._restore_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)

    # ------------------------------------------------------------------
    def _on_create(self):
        note = self._note_edit.text().strip()
        try:
            from src.core.backup_manager import create_backup
            entry = create_backup(self._config, note=note)
        except Exception as exc:
            QMessageBox.critical(self, "Backup Failed", str(exc))
            return

        self._note_edit.clear()
        self._refresh_list()
        QMessageBox.information(
            self,
            "✅ Backup Created",
            f"Backup created successfully.\n\nFile: {entry.label}\nSize: {entry.size_label}",
        )

    # ------------------------------------------------------------------
    def _on_restore(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._entries):
            return

        entry = self._entries[row]
        reply = QMessageBox.question(
            self,
            "Restore Backup",
            f"Restore backup:\n{entry.label}\n\n"
            "This will overwrite existing files in your PCSX2 directories.\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from src.core.backup_manager import restore_backup
            count = restore_backup(entry, self._config)
        except FileNotFoundError:
            QMessageBox.critical(self, "Restore Failed", "Archive file not found on disk.")
            self._refresh_list()
            return
        except Exception as exc:
            QMessageBox.critical(self, "Restore Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "✅ Restore Complete",
            f"Successfully restored {count} file(s) from:\n{entry.label}",
        )

    # ------------------------------------------------------------------
    def _on_delete(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._entries):
            return

        entry = self._entries[row]
        reply = QMessageBox.question(
            self,
            "Delete Backup",
            f"Permanently delete:\n{entry.label}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.backup_manager import delete_backup
        ok = delete_backup(entry)
        if ok:
            self._refresh_list()
        else:
            QMessageBox.warning(self, "Delete Failed", "Could not delete the backup archive.")

    # ------------------------------------------------------------------
    def _on_open_dir(self):
        try:
            from src.core.backup_manager import get_backup_dir
            backup_dir = get_backup_dir(self._config)
        except Exception:
            return

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup_dir)))


# ---------------------------------------------------------------------------
# DownloadHistoryDialog
# ---------------------------------------------------------------------------

class DownloadHistoryDialog(QDialog):
    """Browse, filter and manage the download / installation event history.

    Every successful or failed installation is recorded automatically.  This
    dialog lets the user:

    * View entries with type / status / serial filters.
    * Delete individual entries.
    * Clear the entire history with one click.
    * Export the log to a CSV file.

    Parameters
    ----------
    config:
        Current :class:`~src.models.mod.AppConfig` instance.
    parent:
        Parent widget.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config  = config
        self._entries = []   # list[HistoryEntry] — currently displayed
        self.setWindowTitle("📋  Download History")
        self.setMinimumSize(860, 520)
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "A log of every mod, texture pack, PNACH patch and cover-art image "
            "that was installed through the manager."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        # Filter row
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Status:"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["All", "✅ Success", "❌ Failed", "⏭ Skipped"])
        self._status_combo.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self._status_combo)

        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "All",
            "🎨 Texture Pack",
            "🔧 PNACH Patch",
            "🖼 Cover Art",
            "💾 Game Save",
            "🕹 Cheat",
            "📦 Other",
        ])
        self._type_combo.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self._type_combo)

        filter_row.addWidget(QLabel("Serial:"))
        self._serial_edit = QLineEdit()
        self._serial_edit.setPlaceholderText("e.g. SLUS-20228")
        self._serial_edit.setMaximumWidth(130)
        self._serial_edit.textChanged.connect(self._refresh)
        filter_row.addWidget(self._serial_edit)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Splitter: list (left) + detail (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — entry list
        left  = QWidget()
        ll    = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list_widget)
        splitter.addWidget(left)

        # Right — detail panel
        right = QWidget()
        rl    = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QLabel("← Select an entry from the list")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_label.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self._detail_label, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        rl.addWidget(sep)

        action_row = QHBoxLayout()

        self._delete_btn = QPushButton("🗑  Delete Entry")
        self._delete_btn.setToolTip("Remove this single entry from the history log")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_entry)
        action_row.addWidget(self._delete_btn)

        action_row.addStretch()

        rl.addLayout(action_row)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # Bottom action row
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

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)

        layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _STATUS_MAP = {
        "All": None,
        "✅ Success": "success",
        "❌ Failed":  "failed",
        "⏭ Skipped": "skipped",
    }

    _TYPE_MAP = {
        "All": None,
        "🎨 Texture Pack": "texture_pack",
        "🔧 PNACH Patch":  "pnach",
        "🖼 Cover Art":    "cover_art",
        "💾 Game Save":    "save",
        "🕹 Cheat":        "cheat",
        "📦 Other":        "other",
    }

    def _refresh(self):
        status_text = self._status_combo.currentText()
        type_text   = self._type_combo.currentText()
        serial_text = self._serial_edit.text().strip()

        status_filter   = self._STATUS_MAP.get(status_text)
        mod_type_filter = self._TYPE_MAP.get(type_text)
        serial_filter   = serial_text if serial_text else None

        try:
            from src.core.download_history import list_history
            self._entries = list_history(
                self._config,
                status=status_filter,
                mod_type=mod_type_filter,
                serial=serial_filter,
            )
        except Exception as exc:
            self._entries = []
            self._detail_label.setText(f"<i>Could not read history: {exc}</i>")

        self._list_widget.clear()
        for entry in self._entries:
            label = (
                f"{entry.timestamp[:10]}  {entry.status_label}  "
                f"{entry.type_label}  {entry.mod_name}"
            )
            self._list_widget.addItem(label)

        if not self._entries:
            self._detail_label.setText("<i>No entries found.</i>")

        self._delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._entries):
            self._detail_label.setText("← Select an entry from the list")
            self._delete_btn.setEnabled(False)
            return

        e = self._entries[row]

        color = __import__(
            "src.core.download_history", fromlist=["STATUS_COLOR"]
        ).STATUS_COLOR.get(e.status, "#555")

        html = (
            f"<b>{e.mod_name}</b><br>"
            f"<br>"
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

    # ------------------------------------------------------------------
    def _on_delete_entry(self):
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._entries):
            return

        entry = self._entries[row]
        reply = QMessageBox.question(
            self,
            "Delete Entry",
            f"Remove this entry from the history log?\n\n{entry.mod_name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.download_history import delete_entry
        delete_entry(entry, self._config)
        self._refresh()

    # ------------------------------------------------------------------
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
        count = clear_history(self._config)
        self._refresh()
        QMessageBox.information(
            self,
            "✅ History Cleared",
            f"Removed {count} entr{'y' if count == 1 else 'ies'} from the history log.",
        )

    # ------------------------------------------------------------------
    def _on_export_csv(self):
        from PyQt6.QtWidgets import QFileDialog as _QFD
        path, _ = _QFD.getSaveFileName(
            self,
            "Export History CSV",
            "download_history.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            from src.core.download_history import export_history_csv
            result = export_history_csv(self._config, path=path)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "✅ Export Complete",
            f"History exported to:\n{result}",
        )


class ModNotesDialog(QDialog):
    """View, edit, search and manage personal notes for catalogue entries.

    Notes are persisted in ``mod_notes.json`` next to the application
    executable.  Each note is keyed to a catalogue entry via a stable
    *entry_id* string.

    The dialog lets the user:

    * Browse all notes with optional mod-type and free-text search filters.
    * Create a new note from scratch or edit an existing one.
    * Delete individual notes.
    * Clear all notes at once.
    * Export all notes to a CSV file.

    Parameters
    ----------
    config:
        Current :class:`~src.models.mod.AppConfig` instance.
    parent:
        Parent widget.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._notes  = []   # list[NoteEntry] — currently displayed
        self.setWindowTitle("📝  Mod Notes")
        self.setMinimumSize(900, 560)
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "Write personal notes about texture packs, PNACH patches and other "
            "catalogue entries.  Notes are stored locally and are never shared."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        # Filter row
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "All",
            "🎨 Texture Pack",
            "🔧 PNACH Patch",
            "🖼 Cover Art",
            "💾 Game Save",
            "🕹 Cheat",
            "📦 Other",
        ])
        self._type_combo.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self._type_combo)

        filter_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter by title or note text…")
        self._search_edit.textChanged.connect(self._refresh)
        filter_row.addWidget(self._search_edit, 1)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Splitter: list (left) + editor (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — note list
        left = QWidget()
        ll   = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list_widget)
        splitter.addWidget(left)

        # Right — editor panel
        right = QWidget()
        rl    = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        self._title_label = QLabel("← Select a note or create a new one")
        self._title_label.setWordWrap(True)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        rl.addWidget(self._title_label)

        self._meta_label = QLabel("")
        self._meta_label.setWordWrap(True)
        self._meta_label.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self._meta_label)

        rl.addWidget(QLabel("Note:"))
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("Write your note here…")
        self._text_edit.setEnabled(False)
        rl.addWidget(self._text_edit, 1)

        edit_row = QHBoxLayout()

        self._save_btn = QPushButton("💾 Save Note")
        self._save_btn.setToolTip("Save changes to the current note")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_note)
        edit_row.addWidget(self._save_btn)

        self._delete_btn = QPushButton("🗑  Delete Note")
        self._delete_btn.setToolTip("Permanently remove this note")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_note)
        edit_row.addWidget(self._delete_btn)

        edit_row.addStretch()
        rl.addLayout(edit_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        # Bottom row
        bottom_row = QHBoxLayout()

        new_btn = QPushButton("✏  New Note")
        new_btn.setToolTip("Create a note for a new catalogue entry")
        new_btn.clicked.connect(self._on_new_note)
        bottom_row.addWidget(new_btn)

        clear_btn = QPushButton("🗑  Clear All Notes")
        clear_btn.setToolTip("Delete every note — this cannot be undone")
        clear_btn.clicked.connect(self._on_clear)
        bottom_row.addWidget(clear_btn)

        export_btn = QPushButton("📤 Export CSV")
        export_btn.setToolTip("Save all notes to a CSV file")
        export_btn.clicked.connect(self._on_export_csv)
        bottom_row.addWidget(export_btn)

        bottom_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)

        layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _TYPE_MAP = {
        "All": None,
        "🎨 Texture Pack": "texture_pack",
        "🔧 PNACH Patch":  "pnach",
        "🖼 Cover Art":    "cover_art",
        "💾 Game Save":    "save",
        "🕹 Cheat":        "cheat",
        "📦 Other":        "other",
    }

    def _refresh(self):
        type_text   = self._type_combo.currentText()
        query_text  = self._search_edit.text().strip()
        type_filter = self._TYPE_MAP.get(type_text)

        try:
            from src.core.mod_notes import list_notes
            self._notes = list_notes(
                self._config,
                mod_type=type_filter,
                query=query_text if query_text else None,
            )
        except Exception as exc:
            self._notes = []
            self._meta_label.setText(f"<i>Could not read notes: {exc}</i>")

        self._list_widget.clear()
        for note in self._notes:
            label = f"{note.type_label}  {note.entry_title}"
            if note.serial:
                label += f"  [{note.serial}]"
            self._list_widget.addItem(label)

        # Clear editor
        self._title_label.setText("← Select a note or create a new one")
        self._meta_label.setText("")
        self._text_edit.setEnabled(False)
        self._text_edit.clear()
        self._save_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._notes):
            self._title_label.setText("← Select a note or create a new one")
            self._meta_label.setText("")
            self._text_edit.setEnabled(False)
            self._text_edit.clear()
            self._save_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            return

        note = self._notes[row]
        self._title_label.setText(note.entry_title)
        meta_parts = [f"<b>Type:</b> {note.type_label}"]
        if note.serial:
            meta_parts.append(f"<b>Serial:</b> {note.serial}")
        meta_parts.append(f"<b>Created:</b> {note.created_at[:10]}")
        meta_parts.append(f"<b>Updated:</b> {note.updated_at[:10]}")
        self._meta_label.setText("&nbsp;&nbsp;".join(meta_parts))

        self._text_edit.setEnabled(True)
        self._text_edit.setPlainText(note.text)
        self._save_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        # Store current note for save/delete ops
        self._current_note = note

    # ------------------------------------------------------------------
    def _on_save_note(self):
        note = getattr(self, "_current_note", None)
        if note is None:
            return
        new_text = self._text_edit.toPlainText()
        try:
            from src.core.mod_notes import upsert_note
            upsert_note(
                self._config,
                entry_id    = note.entry_id,
                entry_title = note.entry_title,
                mod_type    = note.mod_type,
                serial      = note.serial,
                text        = new_text,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self._refresh()

    # ------------------------------------------------------------------
    def _on_delete_note(self):
        note = getattr(self, "_current_note", None)
        if note is None:
            return

        reply = QMessageBox.question(
            self,
            "Delete Note",
            f"Permanently delete the note for:\n\n{note.entry_title}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.mod_notes import delete_note
        delete_note(self._config, note.entry_id)
        self._current_note = None
        self._refresh()

    # ------------------------------------------------------------------
    def _on_new_note(self):
        """Open a small input dialog to bootstrap a new note."""
        from PyQt6.QtWidgets import QInputDialog

        title, ok = QInputDialog.getText(
            self, "New Note", "Entry title (mod name):"
        )
        if not ok or not title.strip():
            return

        # Derive a simple slug from the title
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "note"

        # Pick the current type filter or default to "other"
        type_text   = self._type_combo.currentText()
        mod_type    = self._TYPE_MAP.get(type_text) or "other"

        try:
            from src.core.mod_notes import upsert_note
            note = upsert_note(
                self._config,
                entry_id    = slug,
                entry_title = title.strip(),
                mod_type    = mod_type,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        self._refresh()
        # Select the newly created note
        for i, n in enumerate(self._notes):
            if n.entry_id == note.entry_id:
                self._list_widget.setCurrentRow(i)
                break

    # ------------------------------------------------------------------
    def _on_clear(self):
        reply = QMessageBox.question(
            self,
            "Clear All Notes",
            "Delete ALL notes?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.mod_notes import clear_notes
        count = clear_notes(self._config)
        self._current_note = None
        self._refresh()
        QMessageBox.information(
            self,
            "✅ Notes Cleared",
            f"Removed {count} note{'s' if count != 1 else ''}.",
        )

    # ------------------------------------------------------------------
    def _on_export_csv(self):
        from PyQt6.QtWidgets import QFileDialog as _QFD
        path, _ = _QFD.getSaveFileName(
            self,
            "Export Mod Notes CSV",
            "mod_notes.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            from src.core.mod_notes import export_notes_csv
            result = export_notes_csv(self._config, path=path)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "✅ Export Complete",
            f"Notes exported to:\n{result}",
        )
