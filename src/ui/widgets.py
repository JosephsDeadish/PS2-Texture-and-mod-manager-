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
        parent=None,
    ):
        super().__init__(parent)
        self._game_serial = game_serial.strip().upper()
        self._cheats_dir = cheats_dir
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
        self._populate_game_combo()
        game_row.addWidget(self._game_combo, 1)

        load_btn = QPushButton("Load Effects")
        load_btn.setObjectName("primary_btn")
        load_btn.clicked.connect(self._on_load_btn)
        game_row.addWidget(load_btn)
        layout.addLayout(game_row)

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

    def _populate_game_combo(self):
        from src.core.pnach_analyzer import list_all_serials_in_db
        self._game_combo.clear()
        self._game_combo.addItem("— Select a game —", "")
        for serial, title in list_all_serials_in_db():
            self._game_combo.addItem(f"{title}  ({serial})", serial)
        # Pre-select current game
        if self._game_serial:
            for i in range(self._game_combo.count()):
                if self._game_combo.itemData(i) == self._game_serial:
                    self._game_combo.setCurrentIndex(i)
                    break

    def _on_load_btn(self):
        serial = self._game_combo.currentData() or self._game_combo.currentText().strip().upper()
        if serial and serial != "":
            self._load_game(serial)

    # ------------------------------------------------------------------
    # Load entries for the selected game
    # ------------------------------------------------------------------

    def _load_game(self, serial: str):
        from src.core.pnach_analyzer import entries_for_serial
        self._game_serial = serial.strip().upper()
        entries = entries_for_serial(self._game_serial)
        self._render_entries(entries)

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

        desc           = entry.get("description", addr)
        value_map      = entry.get("value_map", {})
        value_type     = entry.get("value_type", "")   # "int" | "float" | "bool" | "button_combo" | ""
        excl_group     = entry.get("exclusion_group", "").strip()
        excl_note      = entry.get("exclusion_note", "").strip()
        input_compat   = entry.get("input_compat", "").strip()
        is_estimated   = entry.get("estimated", True)

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

        # ── Estimated-address warning badge ───────────────────────────
        if is_estimated and value_type in ("button_combo", "bool") and "freecam" in desc.lower():
            est_badge = QLabel("⚠ est.")
            est_badge.setStyleSheet(
                "color: #c09040; font-size: 10px; font-style: italic;"
                " background: #201800; border-radius: 3px; padding: 1px 4px;"
            )
            est_badge.setToolTip(
                "Address is research-estimated — not verified against real hardware "
                "or a community cheat database.\n"
                "Verify with PCSX2: Debug → Memory Search before relying on this code."
            )
            row.addWidget(est_badge)

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
            "check":           chk,
            "value_combo":     value_combo,
            "custom_edit":     custom_edit,
            "value_type":      value_type,
            "crc":             crc,
            "proc":            proc,
            "addr":            addr,
            "description":     desc,
            "value_map":       value_map,
            "exclusion_group": excl_group,
            "exclusion_note":  excl_note,
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
                "processor":       pw["proc"],
                "address":         pw["addr"],
                "value":           hex_val,
                "description":     pw["description"],
                "size":            "extended",
                "crc":             pw["crc"],
                "exclusion_group": pw.get("exclusion_group", ""),
                "exclusion_note":  pw.get("exclusion_note", ""),
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

        # Warn if file already exists
        if os.path.exists(dest):
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
                "Launch PCSX2 and the patch will be applied automatically."
            )
        except OSError as exc:
            QMessageBox.critical(self, "Write Error", f"Could not write PNACH:\n{exc}")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select PCSX2 cheats/ folder",
                                              self._dir_edit.text())
        if d:
            self._dir_edit.setText(d)
