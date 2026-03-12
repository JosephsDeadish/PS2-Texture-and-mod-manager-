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

        # Button row: Code Picker (if PNACH conflicts exist) + Close
        btn_row = QHBoxLayout()
        btn_row.addStretch()

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
