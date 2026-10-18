"""Reusable UI widgets for PS2 Mod Manager."""

import logging
from copy import deepcopy
from html import escape
import os
import textwrap
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, Qt, QSize, pyqtSignal, pyqtSlot, QThread
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

from src.core.game_registry import lookup_game_title
from src.models.mod import ModInfo, ModType, ConflictInfo
from src.ui.tooltips import get_tip

logger = logging.getLogger(__name__)


def _open_local_folder(
    folder: Path,
    parent: QWidget,
    *,
    context: str,
    failure_title: str,
    failure_message: str,
) -> bool:
    """Open *folder* in the system file manager, warning on failure."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    try:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    except Exception as exc:
        logger.warning("Could not open %s folder %s: %s", context, folder, exc)
        QMessageBox.warning(
            parent,
            failure_title,
            f"{failure_message}\n\nPath:\n{folder}\n\nError: {exc}",
        )
        return False

    if not opened:
        logger.warning("Could not open %s folder %s: file manager refused", context, folder)
        QMessageBox.warning(
            parent,
            failure_title,
            f"{failure_message}\n\nPath:\n{folder}\n\nPlease open it manually.",
        )
        return False

    return True

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
                except Exception as exc:
                    logger.warning(
                        "Skipping unreadable PNACH file %s for mod %s: %s",
                        pf_path,
                        mod_id,
                        exc,
                    )
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
    conflicts_requested = pyqtSignal()

    def __init__(
        self,
        mod: ModInfo,
        has_conflict: bool = False,
        is_shadowed: bool = False,
        validation_errors: int = 0,
        validation_warnings: int = 0,
        tooltip_mode: str = "normal",  # "normal" | "dumbed_down" | "no_filter"
        parent=None,
    ):
        super().__init__(parent)
        self.mod = mod
        self.has_conflict = has_conflict
        self.is_shadowed = is_shadowed
        self.validation_errors = validation_errors
        self.validation_warnings = validation_warnings
        self.tooltip_mode = tooltip_mode
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
        name_lbl.setWordWrap(True)
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        name_row.addWidget(name_lbl)
        info.addLayout(name_row)

        badges = QHBoxLayout()
        badges.setSpacing(6)

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
            badges.addWidget(shadow_badge)

        if self.has_conflict:
            warn = QPushButton("⚠ Review conflicts")
            warn.setObjectName("badge")
            warn.setStyleSheet(
                "background:#7a2020; color:#ff8080; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            warn.setToolTip("Review file or PNACH address overlaps between enabled mods in this panel.")
            warn.setAccessibleName(f"Review conflicts for {self.mod.name}")
            warn.clicked.connect(lambda: self.conflicts_requested.emit())
            badges.addWidget(warn)

        if self.validation_errors and not self.is_shadowed:
            n = self.validation_errors
            err_badge = QLabel(f"❌ {n} invalid code{'s' if n != 1 else ''}")
            err_badge.setStyleSheet(
                "background:#5a1010; color:#ff6060; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            err_badge.setToolTip(
                f"{n} code error{'s' if n != 1 else ''} detected (invalid size, bad processor, "
                "value overflow, or non-CRC filename). Correct the source codes and re-import this mod."
            )
            badges.addWidget(err_badge)

        if self.validation_warnings and not self.is_shadowed and not self.validation_errors:
            n = self.validation_warnings
            warn_badge = QLabel(f"⚠ {n} code warning{'s' if n != 1 else ''}")
            warn_badge.setStyleSheet(
                "background:#4a3010; color:#ffb060; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            warn_badge.setToolTip(
                f"{n} code warning{'s' if n != 1 else ''} detected (address out of range, "
                "redundant duplicate). Review this mod's source codes before deploying."
            )
            badges.addWidget(warn_badge)

        if self.mod.has_update:
            upd = QLabel("↑ Update")
            upd.setStyleSheet(
                "background:#1a4a6a; color:#80c8ff; border-radius:9px;"
                "padding: 2px 8px; font-size:11px;"
            )
            badges.addWidget(upd)

        if badges.count():
            badges.addStretch()
            info.addLayout(badges)

        meta_parts = []
        if self.mod.author:
            # Issue #8: distinguish externally-installed mods (no manager record of author)
            if self.mod.author in ("Unknown", "unknown", ""):
                meta_parts.append("by Unknown — may be externally installed")
            else:
                meta_parts.append(f"by {self.mod.author}")
        else:
            meta_parts.append("by Unknown — may be externally installed")
        if self.mod.version:
            meta_parts.append(f"v{self.mod.version}")
        if self.mod.game_id:
            # Issue #23: show the human-readable game title alongside the serial
            _title = lookup_game_title(self.mod.game_id)
            if _title:
                meta_parts.append(f"Game: {self.mod.game_id} — {_title}")
            else:
                meta_parts.append(f"Game: {self.mod.game_id}")
        if self.mod.size_bytes:
            meta_parts.append(_fmt_size(self.mod.size_bytes))

        meta_lbl = QLabel("  •  ".join(meta_parts))
        meta_lbl.setStyleSheet("color: #505070; font-size: 11px;" if self.is_shadowed else "color: #7070a0; font-size: 11px;")
        meta_lbl.setWordWrap(True)
        meta_lbl.setMinimumWidth(0)
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
        up_btn.clicked.connect(lambda: self.priority_up.emit(self.mod.id))
        dn_btn = QPushButton("▼")
        dn_btn.setFixedSize(24, 24)
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
        info_btn.clicked.connect(lambda: self.details_requested.emit(self.mod.id))
        btn_col.addWidget(info_btn)

        edit_btn = QPushButton("✏")
        edit_btn.setFixedSize(28, 28)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.mod.id))
        btn_col.addWidget(edit_btn)

        author_btn = None
        if self.mod.author and self.mod.author != "Unknown":
            author_btn = QPushButton("👤")
            author_btn.setFixedSize(28, 28)
            author_btn.clicked.connect(lambda: self.filter_by_author.emit(self.mod.author))
            btn_col.addWidget(author_btn)

        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(28, 28)
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self.mod.id))
        btn_col.addWidget(del_btn)

        outer.addLayout(btn_col)

        # Toggle
        self.toggle = QCheckBox("Enabled" if self.mod.enabled else "Disabled")
        self.toggle.setAccessibleName(f"Enable or disable {self.mod.name}")
        self.toggle.setChecked(self.mod.enabled)
        self.toggle.toggled.connect(
            lambda enabled: self.toggle.setText("Enabled" if enabled else "Disabled")
        )
        self.toggle.toggled.connect(lambda v: self.toggled.emit(self.mod.id, v))
        outer.addWidget(self.toggle)

        # Apply mode-aware tooltips (issue #31)
        _m = self.tooltip_mode
        up_btn.setToolTip(get_tip("priority_up", _m))
        dn_btn.setToolTip(get_tip("priority_down", _m))
        info_btn.setToolTip(get_tip("details", _m))
        edit_btn.setToolTip(get_tip("edit", _m))
        del_btn.setToolTip(get_tip("remove", _m))
        self.toggle.setToolTip(get_tip("toggle", _m))
        if author_btn is not None:
            author_btn.setToolTip(
                get_tip("author_filter", _m) + f"\n({self.mod.author})"
            )


# ---------------------------------------------------------------------------
# Mod Details Dialog
# ---------------------------------------------------------------------------

class ModDetailsDialog(QDialog):
    """Full-screen details dialog for a mod."""

    # Emitted when the user clicks "See more by [author]" — (author, mod_type_or_None)
    see_more_by_author = pyqtSignal(str, object)
    edit_requested = pyqtSignal(str)

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
        name_lbl = _make_label(self.mod.name, bold=True)
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_lbl.setWordWrap(True)
        title_col.addWidget(name_lbl)
        author_lbl = _make_label(f"by {self.mod.author}  •  v{self.mod.version}")
        author_lbl.setTextFormat(Qt.TextFormat.PlainText)
        author_lbl.setWordWrap(True)
        title_col.addWidget(author_lbl)
        if self.mod.game_id:
            # Issue #23: show game title alongside the serial
            _title = lookup_game_title(self.mod.game_id)
            if _title:
                title_col.addWidget(_make_label(f"Game: {self.mod.game_id} — {_title}"))
            else:
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
                f'<a href="{escape(self.mod.source_url, quote=True)}" style="color:#6090d0;">'
                f"{escape(self.mod.source_url[:60])}</a>"
            )
            src_lbl.setWordWrap(True)
            src_lbl.setOpenExternalLinks(True)
            src_row.addWidget(src_lbl, 1)
            layout.addLayout(src_row)

        # Path
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Location:"))
        path_lbl = QLabel(self.mod.path)
        path_lbl.setTextFormat(Qt.TextFormat.PlainText)
        path_lbl.setWordWrap(True)
        path_row.addWidget(path_lbl, 1)
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
        edit_btn = QPushButton("Edit Metadata")
        edit_btn.clicked.connect(lambda: (self.accept(), self.edit_requested.emit(self.mod.id)))
        btns.addButton(edit_btn, QDialogButtonBox.ButtonRole.ActionRole)
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
    """Review managed-mod overlaps and apply whole-mod changes."""

    def __init__(self, conflicts: list, db, parent=None, pnach_conflicts: list = None,
                 *, manager=None, config=None):
        super().__init__(parent)
        self.db = db
        from src.core.mod_manager import ModManager
        self.manager = manager if manager is not None else ModManager(db)
        self.config = config
        self._busy = False
        self._pairs = self._group_conflicts(conflicts, pnach_conflicts or [])
        self._visible_pairs = []
        self._selected_pair = None
        self._texture_conflicts = [
            conflict for conflict in conflicts
            if all(self.db.get(mid) and self.db.get(mid).mod_type == ModType.TEXTURE_PACK
                   for mid in (conflict.mod_a_id, conflict.mod_b_id))
        ]
        self.pnach_conflicts = pnach_conflicts or []
        self.setWindowTitle("Managed Mod Conflicts")
        self.resize(820, 600)
        self._build_ui()
        self._apply_filters()

    @staticmethod
    def _group_conflicts(conflicts, pnach_conflicts):
        pairs = {}
        for conflict in conflicts:
            key = tuple(sorted((conflict.mod_a_id, conflict.mod_b_id)))
            pair = pairs.setdefault(key, {"files": set(), "addresses": []})
            pair["files"].update(conflict.conflicting_files)
        for entry in pnach_conflicts:
            key = tuple(sorted((entry["mod_a_id"], entry["mod_b_id"])))
            normalized = dict(entry)
            if entry["mod_a_id"] != key[0]:
                normalized["value_a"], normalized["value_b"] = entry.get("value_b", "?"), entry.get("value_a", "?")
            normalized["mod_a_id"], normalized["mod_b_id"] = key
            pairs.setdefault(key, {"files": set(), "addresses": []})["addresses"].append(normalized)
        return pairs

    def _build_ui(self):
        layout = QVBoxLayout(self)
        header = QLabel(
            "Priority affects the whole mod, not just the selected files or addresses. "
            "Overlaps remain visible after prioritizing. This is a review snapshot; "
            "close and reopen to scan again."
        )
        header.setWordWrap(True)
        layout.addWidget(header)
        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search mods, files, CRCs, or addresses…")
        self._search.setAccessibleName("Search managed conflicts")
        self._search.setClearButtonEnabled(True)
        from PyQt6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_filters)
        self._search.textChanged.connect(lambda *_: self._search_timer.start())
        filters.addWidget(self._search, 1)
        self._kind = QComboBox()
        for label, value in (("All overlaps", ""), ("Shared files", "files"), ("PNACH addresses", "addresses")):
            self._kind.addItem(label, value)
        self._kind.setAccessibleName("Filter conflict kind")
        self._kind.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self._kind)
        layout.addLayout(filters)
        clear = QPushButton("Clear Filters")
        clear.clicked.connect(self._clear_filters)
        layout.addWidget(clear)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._pair_list = QListWidget()
        self._pair_list.setWordWrap(True)
        self._pair_list.currentRowChanged.connect(self._on_pair_selected)
        splitter.addWidget(self._pair_list)
        right = QWidget()
        details = QVBoxLayout(right)
        details.setContentsMargins(0, 0, 0, 0)
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumSize(0, 60)
        self._details.setAccessibleName("Managed conflict comparison")
        details.addWidget(self._details, 1)
        self._action_buttons = []
        for action in ("Prioritize", "Disable"):
            row = QHBoxLayout()
            for index, label in enumerate(("A", "B")):
                button = QPushButton(f"{action} {label}")
                button.clicked.connect(lambda _, i=index, a=action: self._apply_action(i, a))
                self._action_buttons.append(button)
                row.addWidget(button)
            details.addLayout(row)
        splitter.addWidget(right)
        splitter.setSizes([280, 540])
        layout.addWidget(splitter, 1)
        self._feedback = QTextEdit()
        self._feedback.setReadOnly(True)
        self._feedback.setAccessibleName("Conflict action result")
        self._feedback.setMaximumHeight(100)
        self._feedback.hide()
        layout.addWidget(self._feedback)
        btn_row = QHBoxLayout()
        if self._texture_conflicts:
            tex_picker_btn = QPushButton("Texture Picker")
            tex_picker_btn.setToolTip(
                "Choose individual textures from all enabled texture conflict pairs and export a merged pack."
            )
            tex_picker_btn.clicked.connect(self._open_texture_picker)
            btn_row.addWidget(tex_picker_btn)
        if self.pnach_conflicts:
            picker_btn = QPushButton("Code Picker")
            picker_btn.setToolTip(
                "Choose individual codes from all enabled PNACH conflict pairs and export merged patches."
            )
            picker_btn.clicked.connect(self._open_code_picker)
            btn_row.addWidget(picker_btn)
        btn_row.addStretch()
        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _apply_filters(self, *_):
        self._search_timer.stop()
        terms = self._search.text().casefold().split()
        kind = self._kind.currentData() or ""
        available = []
        self._visible_pairs = []
        for key, pair in self._pairs.items():
            mods = [self.db.get(mid) for mid in key]
            if not all(mods):
                continue
            available.append(key)
            if kind and not pair[kind]:
                continue
            values = [
                value for mod in mods
                for value in (mod.name, mod.id, mod.author, mod.game_id, mod.mod_type.value)
            ] + list(pair["files"])
            values += [str(entry.get(field, "")) for entry in pair["addresses"]
                       for field in ("game_crc", "processor", "address", "value_a", "value_b")]
            text = "\n".join(values).casefold()
            compact = ["".join(ch for ch in value.casefold() if ch.isalnum()) for value in values]
            if all(term in text or (
                bool(token := "".join(ch for ch in term if ch.isalnum()))
                and any(token in value for value in compact)
            ) for term in terms):
                self._visible_pairs.append(key)
        self._pair_list.blockSignals(True)
        self._pair_list.clear()
        for key in self._visible_pairs:
            a, b = (self.db.get(mid) for mid in key)
            pair = self._pairs[key]
            self._pair_list.addItem(
                f"{a.name} ↔ {b.name}\n{len(pair['files'])} shared file(s) • "
                f"{len(pair['addresses'])} address overlap(s)"
                + ("" if a.enabled and b.enabled else " • Disabled mod")
            )
        if self._visible_pairs:
            index = self._visible_pairs.index(self._selected_pair) if self._selected_pair in self._visible_pairs else 0
            self._pair_list.setCurrentRow(index)
        self._pair_list.blockSignals(False)
        files = sum(len(self._pairs[key]["files"]) for key in available)
        addresses = sum(len(self._pairs[key]["addresses"]) for key in available)
        self._summary.setText(
            f"Showing {len(self._visible_pairs)} of {len(available)} mod pairs • "
            f"{files} shared file references • {addresses} address overlaps"
        )
        self._on_pair_selected(remember=False)

    def _clear_filters(self):
        for widget in (self._search, self._kind):
            widget.blockSignals(True)
        self._search.clear()
        self._kind.setCurrentIndex(0)
        for widget in (self._search, self._kind):
            widget.blockSignals(False)
        self._apply_filters()

    def _current_pair(self):
        row = self._pair_list.currentRow()
        return self._visible_pairs[row] if 0 <= row < len(self._visible_pairs) else None

    def _on_pair_selected(self, *_, remember=True):
        key = self._current_pair()
        mods = [self.db.get(mid) for mid in key] if key else []
        valid = len(mods) == 2 and all(mods)
        for index, button in enumerate(self._action_buttons):
            can_prioritize = valid and all(mod.enabled and mod.mod_type != ModType.SAVE_FILE for mod in mods)
            button.setEnabled(not self._busy and valid and (index >= 2 or can_prioritize))
            if index >= 2 and valid:
                button.setText(f"{'Disable' if mods[index - 2].enabled else 'Retry Disable'} {'AB'[index - 2]}")
        if not valid:
            self._details.setPlainText(
                "No mod pairs match these filters. Use Clear Filters to recover the review."
                if self._pairs else "No overlaps to review."
            )
            return
        if remember or self._selected_pair is None:
            self._selected_pair = key
        pair = self._pairs[key]
        lines = []
        for label, mod in zip(("A", "B"), mods):
            lines.extend((
                f"{label}: {mod.name}", f"{mod.mod_type.value} • {mod.game_id or 'No Game ID'} • "
                f"Priority {mod.priority} • {'Enabled' if mod.enabled else 'Disabled'}",
                f"Storage: {mod.path}", "",
            ))
        if any(mod.mod_type == ModType.SAVE_FILE for mod in mods):
            lines.append("Live memory-card files are never changed here; disabling only changes library state.")
        elif not all(mod.enabled for mod in mods):
            lines.append("A mod in this pair is disabled. Retry Disable to reconcile files after an earlier failure.")
        else:
            lines.append("Higher priority takes precedence in a shared deployment target; equal priorities should be reviewed.")
        lines.extend(("", f"Shared relative files ({len(pair['files'])}):", *sorted(pair["files"]), "",
                      f"PNACH address overlaps ({len(pair['addresses'])}):"))
        for entry in pair["addresses"]:
            lines.append(
                f"CRC {entry.get('game_crc', '?')} • {entry.get('processor', 'EE')} "
                f"0x{entry.get('address', '?')} • A: {entry.get('value_a', '?')} • B: {entry.get('value_b', '?')}"
            )
        self._details.setPlainText("\n".join(lines))

    def _apply_action(self, index, action):
        key = self._current_pair()
        if self._busy or key is None:
            return
        mods = [self.db.get(mid) for mid in key]
        if not all(mods) or index not in (0, 1):
            return
        mod = mods[index]
        if action == "Prioritize" and any(not item.enabled or item.mod_type == ModType.SAVE_FILE for item in mods):
            return
        self._busy = True
        self._on_pair_selected(remember=False)
        message = (
            "This raises priority across the whole library and re-deploys the affected type, "
            "not only the displayed overlap. Other enabled mods remain enabled."
            if action == "Prioritize" else
            "This disables the whole mod and removes its deployed files, then re-deploys remaining mods. "
            "Live memory-card files are not modified."
        )
        reply = QMessageBox.question(
            self, f"{action} Mod",
            f"<p>{action} {escape(mod.name)}?</p><p>{message}</p>"
            "<p>Back up installed content first. Proceed?</p>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._busy = False
            self._on_pair_selected(remember=False)
            return
        try:
            if action == "Prioritize":
                other_priorities = [item.priority for item in self.db.all() if item.id != mod.id and item.enabled]
                priority = max(mod.priority, max(other_priorities, default=mod.priority - 1) + 1)
                count, warnings = self.manager.set_priority(mod.id, priority, self.config)
            else:
                count, warnings = self.manager.set_enabled_many({mod.id: False}, self.config)
        except Exception as exc:
            logger.warning("Could not apply %s to mod %s: %s", action, mod.id, exc)
            self._feedback.setPlainText(
                f"Could not finish {action.lower()}: {exc}\n"
                "Library changes may be saved but installed files may be incomplete. Retry the same action."
            )
        else:
            message = f"{action}: {mod.name} — library state saved."
            if self.config is None:
                message += " No deployment configuration supplied; installed files were not changed."
            elif mod.mod_type == ModType.SAVE_FILE:
                message += " Live memory-card files were not changed."
            elif not warnings:
                message += f" Deployment reconciled ({count} item(s))."
            if warnings:
                message += "\n" + "\n".join(warnings) + "\nCorrect the issue and retry the same action."
            self._feedback.setPlainText(message)
        finally:
            self._busy = False
            self._feedback.show()
            self._apply_filters()

    def _open_texture_picker(self):
        from src.ui.widgets import TextureFilePickerDialog
        conflicts = [
            conflict for conflict in self._texture_conflicts
            if all(self.db.get(mid) and self.db.get(mid).enabled
                   for mid in (conflict.mod_a_id, conflict.mod_b_id))
        ]
        if not conflicts:
            QMessageBox.information(self, "No Enabled Texture Pairs", "No enabled texture pairs remain in this review.")
            return
        dlg = TextureFilePickerDialog(conflicts, self.db, self)
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
        conflicts = [
            entry for entry in self.pnach_conflicts
            if all(self.db.get(mid) and self.db.get(mid).enabled
                   for mid in (entry["mod_a_id"], entry["mod_b_id"]))
        ]
        if not conflicts:
            QMessageBox.information(self, "No Enabled Code Pairs", "No enabled PNACH pairs remain in this review.")
            return
        dlg = PnachCodePickerDialog(conflicts, self.db, self)
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
        cancel_btn.setAccessibleName("Cancel download")
        cancel_btn.setAccessibleDescription("Cancel this download task")
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
        except Exception as exc:
            logger.warning("Could not load library serials for PNACH picker: %s", exc)

        # ── Build full serial→title mapping from serial DB ────────────
        all_serials: dict[str, str] = {}
        try:
            from src.core.serial_validator import SerialDatabase
            sdb = SerialDatabase()
            for title in sdb.all_titles():
                info = sdb.get_info(title)
                if info and info.serial:
                    all_serials[info.serial.upper()] = title
        except Exception as exc:
            logger.warning("Could not load serial database for PNACH picker: %s", exc)
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
                        logger.warning(
                            "Could not convert custom PNACH value for %s (%s): %s",
                            pw.get("description", ""),
                            pw.get("addr", ""),
                            err or raw,
                        )

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

            except Exception as exc:
                logger.warning(
                    "Could not parse existing PNACH file %s while installing %s: %s",
                    dest,
                    crc,
                    exc,
                )
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
            logger.warning("Could not write PNACH file %s while installing %s: %s", dest, crc, exc)
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
            logger.warning("Could not build custom catalogue card: %s", exc)
            self._status.setText(str(exc))
            return

        try:
            out_path = save_entry(entry)
        except Exception as exc:
            logger.warning("Could not save custom catalogue card: %s", exc)
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
            logger.warning("Could not import unmanaged-content scan helpers: %s", exc)
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

class _ConflictScanResult(QObject):
    finished = pyqtSignal(int, object, str)


def _installed_conflict_key(conflict):
    return conflict.conflict_type, tuple(sorted(str(path) for path in conflict.items))


def _installed_conflict_matches(conflict, query):
    values = (
        conflict.title, conflict.description, conflict.resolution,
        conflict.conflict_type, conflict.severity_label,
        *(str(path) for path in conflict.items),
    )
    text = "\n".join(values).casefold()
    compact = tuple("".join(ch for ch in value.casefold() if ch.isalnum()) for value in values)
    return all(
        term in text or (
            bool(key := "".join(ch for ch in term if ch.isalnum()))
            and any(key in value for value in compact)
        )
        for term in query.casefold().split()
    )


class ConflictResolverDialog(QDialog):
    """Scans installed PCSX2 content for conflicts — situations where two or
    more items would interfere with each other at runtime.

    Detected conflict types include:

    * Duplicate CRC ``.pnach`` files in both ``cheats/`` and ``cheats_ws/``
    * Two ``.pnach`` files patching the **same EE memory address** for the same CRC
    * Multiple cover-art images for the same PS2 serial
    * Duplicate texture files with identical content inside replacements folders

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
        self._config = config
        self._conflicts = []
        self._visible_conflicts = []
        self._selected_key = None
        self._scanning = False
        self._fixing = False
        self._closed = False
        self._scan_id = 0
        self._scan_error = ""
        from PyQt6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_filters)
        self.setWindowTitle("⚠  Conflict Resolver")
        self.resize(800, 560)
        self._build_ui()
        self._run_scan()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(
            "Review conflicts in configured PCSX2 folders. Search titles, serials, "
            "CRCs, descriptions, or file paths. Filters only change this list; "
            "Auto-Fix affects the selected conflict."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)
        filter_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search conflicts or files…")
        self._search_edit.setAccessibleName("Search installed conflicts")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda *_: self._search_timer.start())
        filter_row.addWidget(self._search_edit, 1)
        self._severity_combo = QComboBox()
        for label, value in (
            ("All severities", ""), ("Errors", "error"),
            ("Warnings", "warning"), ("Info", "info"),
        ):
            self._severity_combo.addItem(label, value)
        self._severity_combo.setAccessibleName("Filter conflicts by severity")
        self._severity_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._severity_combo)
        layout.addLayout(filter_row)
        recovery_row = QHBoxLayout()
        self._autofix_only = QCheckBox("Auto-fixable only")
        self._autofix_only.toggled.connect(self._apply_filters)
        recovery_row.addWidget(self._autofix_only)
        recovery_row.addStretch()
        clear_btn = QPushButton("Clear Filters")
        clear_btn.clicked.connect(self._clear_filters)
        recovery_row.addWidget(clear_btn)
        self._rescan_btn = QPushButton("Re-scan")
        self._rescan_btn.clicked.connect(self._run_scan)
        recovery_row.addWidget(self._rescan_btn)
        layout.addLayout(recovery_row)
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        # Splitter: conflict list (left) + detail panel (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: list of conflicts ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.setWordWrap(True)
        self._list_widget.currentRowChanged.connect(self._on_conflict_selected)
        left_layout.addWidget(self._list_widget)

        splitter.addWidget(left)

        # --- Right: detail panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QTextEdit()
        self._detail_label.setReadOnly(True)
        self._detail_label.setMinimumSize(0, 60)
        self._detail_label.setAccessibleName("Conflict details")
        right_layout.addWidget(self._detail_label, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep)

        # Resolution row
        res_lbl = QLabel("<b>Suggested Resolution:</b>")
        right_layout.addWidget(res_lbl)

        self._resolution_label = QLabel("")
        self._resolution_label.setWordWrap(True)
        self._resolution_label.setTextFormat(Qt.TextFormat.PlainText)
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

        self._open_folder_btn = QPushButton("📂 Open Folder")
        self._open_folder_btn.setToolTip("Open the selected file's folder, or the first involved folder")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        action_row.addWidget(self._open_folder_btn)
        action_row.addStretch()
        right_layout.addLayout(action_row)
        self._copy_files_btn = QPushButton("Copy Paths")
        self._copy_files_btn.setToolTip("Copy all file paths for the selected conflict")
        self._copy_files_btn.clicked.connect(self._on_copy_paths)
        right_layout.addWidget(self._copy_files_btn)

        splitter.addWidget(right)
        splitter.setSizes([280, 560])
        layout.addWidget(splitter, 1)

        # Close button
        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    # ------------------------------------------------------------------
    def _run_scan(self):
        if self._closed or self._scanning or self._fixing:
            return
        import threading
        self._search_timer.stop()
        self._scanning = True
        self._scan_error = ""
        self._scan_id += 1
        scan_id = self._scan_id
        config = deepcopy(self._config)
        self._conflicts = []
        self._visible_conflicts = []
        self._list_widget.clear()
        self._summary_label.setText("Scanning configured folders…")
        self._detail_label.setPlainText("Scanning in the background. You can change filters or close this window.")
        self._resolution_label.setText("")
        self._files_list.clear()
        self._autofix_btn.setEnabled(False)
        self._open_folder_btn.setEnabled(False)
        self._copy_files_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)
        # Keep the relay alive independently of the dialog during filesystem I/O.
        result = _ConflictScanResult()
        result.finished.connect(self._on_scan_finished)

        def run():
            conflicts, error = [], ""
            try:
                from src.core.conflict_resolver import resolve_all_conflicts
                conflicts = resolve_all_conflicts(config)
            except Exception as exc:
                logger.warning("Could not scan installed conflicts: %s", exc)
                error = str(exc) or type(exc).__name__
            result.finished.emit(scan_id, conflicts, error)
            result.deleteLater()

        try:
            threading.Thread(target=run, daemon=True).start()
        except RuntimeError as exc:
            logger.warning("Could not start installed-conflict scan: %s", exc)
            result.deleteLater()
            self._on_scan_finished(scan_id, [], str(exc) or type(exc).__name__)

    @pyqtSlot(int, object, str)
    def _on_scan_finished(self, scan_id, conflicts, error):
        if self._closed or scan_id != self._scan_id:
            return
        self._scanning = False
        self._scan_error = error
        self._conflicts = list(conflicts) if not error else []
        self._rescan_btn.setEnabled(True)
        self._apply_filters()

    def _apply_filters(self, *_):
        self._search_timer.stop()
        if self._scanning or self._closed:
            return
        query = self._search_edit.text()
        severity = self._severity_combo.currentData() or ""
        fixable = self._autofix_only.isChecked()
        if self._selected_key not in {_installed_conflict_key(c) for c in self._conflicts}:
            self._selected_key = None
        self._visible_conflicts = [
            conflict for conflict in self._conflicts
            if (not severity or conflict.severity == severity)
            and (not fixable or conflict.can_auto_fix)
            and _installed_conflict_matches(conflict, query)
        ]
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        for conflict in self._visible_conflicts:
            item = QListWidgetItem(
                f"{conflict.severity_label}  {conflict.title}\n"
                f"{len(conflict.items)} file(s) • "
                + ("Auto-fix available" if conflict.can_auto_fix else "Manual review")
            )
            item.setToolTip("\n".join(str(path) for path in conflict.items))
            self._list_widget.addItem(item)
        keys = [_installed_conflict_key(conflict) for conflict in self._visible_conflicts]
        if keys:
            self._list_widget.setCurrentRow(keys.index(self._selected_key) if self._selected_key in keys else 0)
        self._list_widget.blockSignals(False)
        counts = [f"{sum(c.severity == value for c in self._conflicts)} {value}" for value in ("error", "warning", "info")]
        self._summary_label.setText(
            f"Showing {len(keys)} of {len(self._conflicts)} conflicts • " + ", ".join(counts)
            if not self._scan_error else "Scan failed — use Re-scan to retry."
        )
        self._on_conflict_selected(self._list_widget.currentRow(), remember=False)

    def _clear_filters(self):
        for widget in (self._search_edit, self._severity_combo, self._autofix_only):
            widget.blockSignals(True)
        self._search_edit.clear()
        self._severity_combo.setCurrentIndex(0)
        self._autofix_only.setChecked(False)
        for widget in (self._search_edit, self._severity_combo, self._autofix_only):
            widget.blockSignals(False)
        self._apply_filters()

    def _selected_conflict(self):
        if self._closed or self._scanning or self._fixing:
            return None
        row = self._list_widget.currentRow()
        return self._visible_conflicts[row] if 0 <= row < len(self._visible_conflicts) else None

    # ------------------------------------------------------------------
    def _on_conflict_selected(self, row: int, remember=True):
        conflict = self._selected_conflict()
        self._autofix_btn.setEnabled(bool(conflict and conflict.can_auto_fix))
        self._open_folder_btn.setEnabled(bool(conflict and conflict.items))
        self._copy_files_btn.setEnabled(bool(conflict and conflict.items))
        self._files_list.clear()
        if conflict is None:
            self._resolution_label.clear()
            if self._scan_error:
                message = f"Scan failed: {self._scan_error}\nUse Re-scan to retry. No fixes are available from a failed scan."
            elif self._conflicts:
                message = "No conflicts match these filters. Use Clear Filters to show all scan results."
            elif not any(getattr(self._config, name, "") for name in (
                "pnach_path", "cheats_path", "textures_path", "cover_art_path",
            )):
                message = "No PCSX2 content folders are configured. Set the paths in Settings, then Re-scan."
            else:
                message = "No conflicts found in configured folders.\nUnreadable or missing content may be skipped; see the log for scan warnings."
            self._detail_label.setPlainText(message)
            return

        if remember or self._selected_key is None:
            self._selected_key = _installed_conflict_key(conflict)
        self._detail_label.setPlainText(
            f"{conflict.severity_label}\n{conflict.title}\n\n{conflict.description}"
        )
        self._resolution_label.setText(conflict.resolution)
        for path in conflict.items:
            self._files_list.addItem(str(path))
        if conflict.items:
            self._files_list.setCurrentRow(0)

    # ------------------------------------------------------------------
    def _on_auto_fix(self):
        conflict = self._selected_conflict()
        if conflict is None or not conflict.can_auto_fix:
            return

        self._fixing = True
        self._autofix_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)
        reply = QMessageBox.question(
            self,
            "Auto-Fix Conflict",
            f"<p>Auto-fix '{escape(conflict.title)}'?</p>"
            f"<p>{escape(conflict.resolution)}</p>"
            "This can modify or delete the involved files. Back them up first. Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._fixing = False
            self._rescan_btn.setEnabled(True)
            self._apply_filters()
            return

        try:
            from src.core.conflict_resolver import auto_fix_conflict
            ok, message = auto_fix_conflict(conflict)
        except Exception as exc:
            logger.warning("Could not auto-fix conflict %s: %s", conflict.conflict_type, exc)
            QMessageBox.critical(self, "Auto-Fix Error", f"<p>{escape(str(exc))}</p>")
        else:
            if ok:
                QMessageBox.information(self, "✅ Fixed", f"<p>{escape(message)}</p>")
            else:
                QMessageBox.warning(self, "Auto-Fix Failed", f"<p>{escape(message)}</p>")
        finally:
            self._fixing = False
            self._run_scan()

    # ------------------------------------------------------------------
    def _on_open_folder(self):
        conflict = self._selected_conflict()
        if conflict is None or not conflict.items:
            return

        row = self._files_list.currentRow()
        path = Path(conflict.items[row if 0 <= row < len(conflict.items) else 0])
        folder = path if path.is_dir() else path.parent
        _open_local_folder(
            folder,
            self,
            context="conflict",
            failure_title="Folder Unavailable",
            failure_message="Could not open the folder for the selected conflict.",
        )

    def _on_copy_paths(self):
        conflict = self._selected_conflict()
        if conflict and conflict.items:
            QApplication.clipboard().setText("\n".join(str(path) for path in conflict.items))

    def done(self, result):
        self._closed = True
        self._search_timer.stop()
        super().done(result)


# ---------------------------------------------------------------------------
# BackupManagerDialog
# ---------------------------------------------------------------------------

class _BackupOperationResult(QObject):
    finished = pyqtSignal(str, object, str)


def _backup_matches(entry, query):
    values = (entry.label, entry.note, entry.path, entry.created_at)
    compact = ["".join(ch for ch in value.casefold() if ch.isalnum()) for value in values]
    return all(
        any(term in value.casefold() for value in values)
        or bool(key := "".join(ch for ch in term if ch.isalnum()))
        and any(key in value for value in compact)
        for term in query.casefold().split()
    )


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
        self._shown_entries = []
        self._selected_path = ""
        self._busy = ""
        self._confirming = False
        self._loaded = False
        self._load_error = ""
        self._result_text = ""
        self.setWindowTitle("💾  Backup Manager")
        self.setMinimumSize(640, 440)
        self.resize(900, 600)
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

        controls = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search archive names, notes, dates, or paths…")
        self._search_edit.setClearButtonEnabled(True)
        controls.addWidget(self._search_edit, 1)
        self._sort_combo = QComboBox()
        for label, key in (
            ("Newest first", "newest"), ("Oldest first", "oldest"),
            ("Name A–Z", "name"), ("Largest first", "size"),
        ):
            self._sort_combo.addItem(label, key)
        self._sort_combo.currentIndexChanged.connect(self._apply_filters)
        controls.addWidget(self._sort_combo)
        self._clear_btn = QPushButton("Clear Filters")
        self._clear_btn.clicked.connect(self._clear_filters)
        controls.addWidget(self._clear_btn)
        self._reload_btn = QPushButton("Reload Backups")
        self._reload_btn.clicked.connect(self._refresh_list)
        controls.addWidget(self._reload_btn)
        layout.addLayout(controls)

        from PyQt6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_filters)
        self._search_edit.textChanged.connect(lambda: self._search_timer.start())
        self._count_label = QLabel()
        layout.addWidget(self._count_label)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status_label)
        self._result_label = QTextEdit()
        self._result_label.setReadOnly(True)
        self._result_label.setMaximumHeight(110)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

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

        self._create_btn = QPushButton("➕ Create Backup")
        self._create_btn.setObjectName("primary_btn")
        self._create_btn.setToolTip("Create a new archive without replacing existing backups")
        self._create_btn.clicked.connect(self._on_create)
        create_row.addWidget(self._create_btn)

        left_layout.addLayout(create_row)
        splitter.addWidget(left)

        # --- Right: detail panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_label = QTextEdit()
        self._detail_label.setReadOnly(True)
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

        open_dir_btn = QPushButton("📂 Open Backups Folder")
        open_dir_btn.setToolTip("Open the backups folder in the file manager")
        open_dir_btn.clicked.connect(self._on_open_dir)
        right_layout.addLayout(action_row)
        right_layout.addWidget(open_dir_btn)
        self._copy_path_btn = QPushButton("Copy Archive Path")
        self._copy_path_btn.clicked.connect(self._copy_path)
        right_layout.addWidget(self._copy_path_btn)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        # Close button
        close_row = QHBoxLayout()
        self._copy_result_btn = QPushButton("Copy Last Result")
        self._copy_result_btn.setEnabled(False)
        self._copy_result_btn.clicked.connect(self._copy_result)
        close_row.addWidget(self._copy_result_btn)
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ------------------------------------------------------------------
    def _refresh_list(self):
        if self._busy or self._confirming:
            return
        from src.core.backup_manager import list_backups
        config = deepcopy(self._config)
        self._start_operation("list", lambda: list_backups(config))

    def _selected_entry(self):
        row = self._list_widget.currentRow()
        return self._shown_entries[row] if 0 <= row < len(self._shown_entries) else None

    def _apply_filters(self, *_):
        self._search_timer.stop()
        query = self._search_edit.text().strip()
        entries = [entry for entry in self._entries if _backup_matches(entry, query)]
        sort = self._sort_combo.currentData()
        if sort == "name":
            entries.sort(key=lambda entry: (entry.label.casefold(), entry.path))
        elif sort == "size":
            entries.sort(key=lambda entry: (-entry.size_bytes, entry.label.casefold(), entry.path))
        else:
            entries.sort(key=lambda entry: (entry.created_at, entry.label, entry.path),
                         reverse=sort != "oldest")
        self._shown_entries = entries
        self._list_widget.blockSignals(True)
        try:
            self._list_widget.clear()
            selected = -1
            for row, entry in enumerate(entries):
                state = "Unreadable ZIP" if entry.inspection_error else f"{entry.file_count} files"
                self._list_widget.addItem(
                    f"{entry.label}\n{entry.created_at} • {entry.size_label} • {state}"
                )
                if entry.path == self._selected_path:
                    selected = row
            self._list_widget.setCurrentRow(selected)
        finally:
            self._list_widget.blockSignals(False)
        self._count_label.setText(f"Showing {len(entries)} of {len(self._entries)} backups")
        self._clear_btn.setEnabled(bool(query) or sort != "newest")
        self._on_selection_changed(selected)

    def _on_selection_changed(self, row: int):
        entry = self._selected_entry()
        if entry is not None:
            self._selected_path = entry.path
            size_kind = "Archive on disk" if entry.inspection_error else "Uncompressed size"
            text = (
                f"{entry.label}\n\nDate (archive modified): {entry.created_at}\n"
                f"{size_kind}: {entry.size_label}\nFiles listed: {entry.file_count}\n"
                f"Note: {entry.note or '—'}\n\nArchive path:\n{entry.path}"
            )
            if entry.inspection_error:
                text += f"\n\nCould not read ZIP index: {entry.inspection_error}\nReload after repairing the archive."
            else:
                text += "\n\nZIP index readable; file contents have not been integrity-checked."
        elif self._entries and not self._shown_entries:
            text = "No matching backups. Use Clear Filters to show all archives."
        elif not self._entries and self._loaded:
            text = "No backups found. Add an optional note and choose Create Backup."
        else:
            text = "Select a backup to inspect its details."
        self._detail_label.setPlainText(text)
        self._update_actions()

    def _clear_filters(self):
        self._search_edit.clear()
        self._sort_combo.setCurrentIndex(0)
        self._apply_filters()

    def _update_actions(self):
        ready = not self._busy and not self._confirming
        entry = self._selected_entry()
        current = ready and self._loaded and not self._load_error and entry is not None
        self._restore_btn.setEnabled(bool(current and not entry.inspection_error and entry.file_count))
        self._delete_btn.setEnabled(bool(current))
        self._copy_path_btn.setEnabled(entry is not None)
        self._create_btn.setEnabled(ready)
        self._note_edit.setEnabled(ready)
        self._reload_btn.setEnabled(ready)

    def _set_result(self, text):
        self._result_text = text
        self._result_label.setPlainText(text)
        self._result_label.setVisible(bool(text))
        self._copy_result_btn.setEnabled(bool(text))

    def _copy_path(self):
        entry = self._selected_entry()
        if entry is not None:
            QApplication.clipboard().setText(entry.path)

    def _copy_result(self):
        QApplication.clipboard().setText(self._result_text)

    def _start_operation(self, kind, work, details=""):
        import threading
        if self._busy or self._confirming:
            return
        relay = _BackupOperationResult()
        relay.finished.connect(self._operation_finished)
        self._busy = kind
        self._operation_details = details
        labels = {"list": "Reading backup archives…", "create": "Creating backup…",
                  "restore": "Restoring backup…", "delete": "Deleting backup…"}
        self._status_label.setText(labels[kind])
        self._update_actions()

        def run():
            try:
                result, error = work(), ""
            except Exception as exc:
                logger.warning("Backup %s failed: %s", kind, exc)
                result, error = None, str(exc) or type(exc).__name__
            relay.finished.emit(kind, result, error)
            relay.deleteLater()

        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception as exc:
            relay.deleteLater()
            self._operation_finished(kind, None, str(exc) or type(exc).__name__)

    @pyqtSlot(str, object, str)
    def _operation_finished(self, kind, result, error):
        self._busy = ""
        if kind == "list":
            self._load_error = error
            if not error:
                self._entries = result
                self._loaded = True
                if not any(entry.path == self._selected_path for entry in result):
                    self._selected_path = ""
            self._status_label.setText(
                f"Could not read backups: {error}\nPrevious results kept. Use Reload Backups to retry."
                if error else "Ready. Close PCSX2 before creating or restoring archives."
            )
            self._apply_filters()
            return
        if error:
            self._set_result(
                f"{kind.title()} failed: {error}\n"
                + ("Some files may already have changed. Check destinations before retrying."
                   if kind == "restore" else "Check the error and retry the action.")
            )
        elif kind == "create":
            self._selected_path = result.path
            self._note_edit.clear()
            self._set_result(
                f"Created {result.label}: {result.file_count} files; "
                f"{result.failure_count} recoverable issue(s).\n{result.path}\n"
                + ("Backup may be incomplete. See the application log for details."
                   if result.failure_count else
                   "Archive is empty; no source files were included." if not result.file_count else
                   "Existing archives were not replaced.")
            )
        elif kind == "restore":
            self._set_result(
                f"Restore finished: {result.restored} restored, {result.failed} failed, "
                f"{result.skipped} skipped.\n"
                "Skipped files include unknown destination folders and unsafe paths. "
                "See the application log for failures. This does not change mod enabled flags."
            )
        elif result:
            self._set_result("Backup archive deleted.")
            self._selected_path = ""
        else:
            self._set_result("Delete failed. The archive may be missing or inaccessible. Reload and retry.")
        if self._operation_details:
            self._set_result(f"{self._result_text}\n\n{self._operation_details}")
        self._update_actions()
        self._refresh_list()

    def _confirm_action(self, title, text, details):
        self._confirming = True
        self._update_actions()
        try:
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(text)
            box.setDetailedText(details)
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            return box.exec() == QMessageBox.StandardButton.Yes
        finally:
            self._confirming = False
            self._update_actions()

    # ------------------------------------------------------------------
    def _on_create(self):
        if self._busy or self._confirming:
            return
        note = self._note_edit.text().strip()
        from src.core.backup_manager import create_backup
        config = deepcopy(self._config)
        self._start_operation("create", lambda: create_backup(config, note=note))

    # ------------------------------------------------------------------
    def _on_restore(self):
        entry = self._selected_entry()
        if (self._busy or self._confirming or self._load_error or entry is None
                or entry.inspection_error or not entry.file_count):
            return
        config = deepcopy(self._config)
        destinations = "\n".join(
            f"{attr}: {getattr(config, attr, '') or '(not configured)'}"
            for attr in ("pnach_path", "cheats_path", "cover_art_path", "textures_path")
        )
        if not self._confirm_action(
            "Restore Backup",
            f"Restore {entry.label}?\n\nClose PCSX2 first. Existing destination files may be overwritten. "
            "There is no automatic undo; create a backup first if needed.\n"
            "Archive folders match the names of current destination folders; unmatched files are skipped. "
            "Mod library flags and memory cards are not restored.",
            f"Archive:\n{entry.path}\n\nCurrent destination settings:\n{destinations}",
        ):
            return
        from src.core.backup_manager import restore_backup
        self._start_operation(
            "restore", lambda: restore_backup(entry, config, detailed=True),
            f"Archive:\n{entry.path}\n\nDestination settings used:\n{destinations}",
        )

    # ------------------------------------------------------------------
    def _on_delete(self):
        entry = self._selected_entry()
        if self._busy or self._confirming or self._load_error or entry is None:
            return
        if not self._confirm_action(
            "Delete Backup", f"Permanently delete {entry.label}?\n\nThis cannot be undone.",
            f"Only this archive will be deleted:\n{entry.path}",
        ):
            return
        from src.core.backup_manager import delete_backup
        self._start_operation("delete", lambda: delete_backup(entry), f"Archive:\n{entry.path}")

    def reject(self):
        if self._confirming or self._busy in ("create", "restore", "delete"):
            self._status_label.setText("Please wait for the file operation to finish before closing.")
            return
        super().reject()

    def closeEvent(self, event):
        if self._confirming or self._busy in ("create", "restore", "delete"):
            self._status_label.setText("Please wait for the file operation to finish before closing.")
            event.ignore()
        else:
            super().closeEvent(event)

    # ------------------------------------------------------------------
    def _on_open_dir(self):
        try:
            from src.core.backup_manager import get_backup_dir
            backup_dir = get_backup_dir(self._config)
        except Exception as exc:
            logger.warning("Could not determine backup directory: %s", exc)
            return

        _open_local_folder(
            backup_dir,
            self,
            context="backup",
            failure_title="Backup Folder Unavailable",
            failure_message="Could not open the backup folder.",
        )


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
            logger.warning("Could not load download history: %s", exc)
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
            logger.warning("Could not export download history CSV to %s: %s", path, exc)
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
        self._all_notes = []
        self._notes = []
        self._current_note = None
        self._changing_note = False
        from PyQt6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_filters)
        self.setWindowTitle("📝  Mod Notes")
        self.setMinimumSize(620, 420)
        self.resize(900, 600)
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
        self._type_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self._type_combo)

        filter_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search titles, notes, serials, or IDs…")
        self._search_edit.setAccessibleName("Search mod notes")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda *_: self._search_timer.start())
        filter_row.addWidget(self._search_edit, 1)
        layout.addLayout(filter_row)
        tools = QHBoxLayout()
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Recently updated", "Oldest updated", "Title (A–Z)"])
        self._sort_combo.setAccessibleName("Sort mod notes")
        self._sort_combo.currentIndexChanged.connect(self._apply_filters)
        tools.addWidget(self._sort_combo)
        clear_filters = QPushButton("Clear Filters")
        clear_filters.clicked.connect(self._clear_filters)
        tools.addWidget(clear_filters)
        refresh_btn = QPushButton("Reload Notes")
        refresh_btn.clicked.connect(self._refresh)
        tools.addWidget(refresh_btn)
        tools.addStretch()
        layout.addLayout(tools)
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._summary_label)

        # Splitter: list (left) + editor (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — note list
        left = QWidget()
        ll   = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.setWordWrap(True)
        self._list_widget.setAccessibleName("Saved mod notes")
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list_widget)
        splitter.addWidget(left)

        # Right — editor panel
        right = QWidget()
        rl    = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        self._title_label = QLabel("← Select a note or create a new one")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(True)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        rl.addWidget(self._title_label)

        self._meta_label = QLabel("")
        self._meta_label.setWordWrap(True)
        self._meta_label.setTextFormat(Qt.TextFormat.PlainText)
        rl.addWidget(self._meta_label)
        self._draft_label = QLabel()
        self._draft_label.setWordWrap(True)
        rl.addWidget(self._draft_label)

        rl.addWidget(QLabel("Note:"))
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("Write your note here…")
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setAccessibleName("Note text")
        self._text_edit.setEnabled(False)
        self._text_edit.textChanged.connect(self._sync_editor_state)
        rl.addWidget(self._text_edit, 1)

        edit_row = QHBoxLayout()

        self._save_btn = QPushButton("💾 Save Note")
        self._save_btn.setToolTip("Save changes to the current note")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_note)
        edit_row.addWidget(self._save_btn)
        self._revert_btn = QPushButton("Revert")
        self._revert_btn.clicked.connect(self._on_revert)
        self._revert_btn.setEnabled(False)
        edit_row.addWidget(self._revert_btn)

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
        export_btn.setToolTip("Export every saved note, including hidden notes; unsaved drafts are not included")
        export_btn.clicked.connect(self._on_export_csv)
        bottom_row.addWidget(export_btn)

        bottom_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)

        layout.addLayout(bottom_row)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status_label)

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
        if not self._confirm_leave():
            return
        try:
            from src.core.mod_notes import list_notes
            notes = list_notes(self._config, strict=True)
        except Exception as exc:
            logger.warning("Could not refresh mod notes list: %s", exc)
            self._status_label.setText(f"Could not read notes: {exc}\nPrevious results are kept. Use Reload Notes to retry.")
            return
        selected_id = self._current_note.entry_id if self._current_note else None
        self._all_notes = notes
        self._show_note(next((note for note in notes if note.entry_id == selected_id), None))
        self._status_label.setText("")
        self._apply_filters()

    def _apply_filters(self, *_):
        self._search_timer.stop()
        terms = self._search_edit.text().casefold().split()
        mod_type = self._TYPE_MAP.get(self._type_combo.currentText())
        self._notes = [
            note for note in self._all_notes
            if (not mod_type or note.mod_type == mod_type or
                (mod_type == "save" and note.mod_type == "save_file"))
            and all(term in " ".join((
                note.entry_title, note.text, note.serial, note.entry_id, note.type_label,
            )).casefold() for term in terms)
        ]
        sort = self._sort_combo.currentText()
        if sort == "Title (A–Z)":
            self._notes.sort(key=lambda note: (note.entry_title.casefold(), note.entry_id))
        else:
            self._notes.sort(key=lambda note: (note.updated_at, note.entry_id), reverse=sort != "Oldest updated")
        selected_id = self._current_note.entry_id if self._current_note else None
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        for index, note in enumerate(self._notes):
            label = f"{note.entry_title}\n{note.type_label}"
            if note.serial:
                label += f" • {note.serial}"
            preview = " ".join(note.text.split())[:80]
            if preview:
                label += f"\n{preview}"
            item = QListWidgetItem(label)
            item.setToolTip(f"{note.entry_title}\nEntry ID: {note.entry_id}")
            self._list_widget.addItem(item)
            if note.entry_id == selected_id:
                self._list_widget.setCurrentRow(index)
        self._list_widget.blockSignals(False)
        summary = f"Showing {len(self._notes)} of {len(self._all_notes)} notes."
        if not self._all_notes:
            summary += " Use New Note to create one."
        elif not self._notes:
            summary += " No matches — use Clear Filters."
        self._summary_label.setText(summary)
        self._sync_editor_state()

    def _clear_filters(self):
        self._search_edit.clear()
        self._type_combo.setCurrentIndex(0)
        self._apply_filters()

    def _is_dirty(self):
        return self._current_note is not None and self._text_edit.toPlainText() != self._current_note.text

    def _sync_editor_state(self):
        dirty = self._is_dirty()
        self._save_btn.setEnabled(dirty)
        self._revert_btn.setEnabled(dirty)
        self._delete_btn.setEnabled(self._current_note is not None)
        text = "Unsaved changes" if dirty else "Saved" if self._current_note else ""
        if self._current_note and not any(note.entry_id == self._current_note.entry_id for note in self._notes):
            text += " • Editing a note hidden by the current filters."
        self._draft_label.setText(text)

    def _show_note(self, note):
        self._current_note = note
        self._title_label.setText(note.entry_title if note else "← Select a note or create a new one")
        self._meta_label.setText(
            f"{note.type_label} • {note.serial or 'No serial'}\n"
            f"Created: {note.created_at[:10]} • Updated: {note.updated_at[:10]}"
            if note else ""
        )
        self._text_edit.blockSignals(True)
        self._text_edit.setPlainText(note.text if note else "")
        self._text_edit.setEnabled(note is not None)
        self._text_edit.blockSignals(False)
        self._sync_editor_state()

    def _confirm_leave(self):
        if self._changing_note:
            return False
        if not self._is_dirty():
            return True
        self._changing_note = True
        try:
            reply = QMessageBox.question(
                self, "Unsaved Note",
                f"Save changes to:\n{self._current_note.entry_title}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                return self._save_current_note()
            return reply == QMessageBox.StandardButton.Discard
        finally:
            self._changing_note = False

    def done(self, result):
        if self._confirm_leave():
            self._search_timer.stop()
            super().done(result)

    def _on_revert(self):
        if self._is_dirty() and QMessageBox.question(
            self, "Revert Note", "Discard the unsaved changes to this note?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._show_note(self._current_note)
            self._status_label.setText("Changes reverted.")

    # ------------------------------------------------------------------
    def _on_selection_changed(self, row: int):
        if self._changing_note or row < 0 or row >= len(self._notes):
            return
        note = self._notes[row]
        if self._current_note and note.entry_id == self._current_note.entry_id:
            return
        if self._confirm_leave():
            self._show_note(note)
            self._status_label.setText("")
        self._apply_filters()

    # ------------------------------------------------------------------
    def _on_save_note(self):
        self._save_current_note()

    def _save_current_note(self):
        note = self._current_note
        if note is None:
            return False
        if not self._is_dirty():
            return True
        new_text = self._text_edit.toPlainText()
        try:
            from src.core.mod_notes import upsert_note
            saved = upsert_note(
                self._config,
                entry_id    = note.entry_id,
                entry_title = note.entry_title,
                mod_type    = note.mod_type,
                serial      = note.serial,
                text        = new_text,
            )
        except Exception as exc:
            logger.warning("Could not save mod note %s: %s", note.entry_id, exc)
            self._status_label.setText(f"Could not save note: {exc}\nYour draft is kept. Use Save Note to retry.")
            QMessageBox.critical(self, "Save Failed", str(exc))
            return False
        self._all_notes = [saved if item.entry_id == saved.entry_id else item for item in self._all_notes]
        self._show_note(saved)
        self._apply_filters()
        self._status_label.setText("Note saved.")
        return True

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
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from src.core.mod_notes import delete_note
            delete_note(self._config, note.entry_id)
        except Exception as exc:
            logger.warning("Could not delete mod note %s: %s", note.entry_id, exc)
            self._status_label.setText(f"Could not delete note: {exc}\nYour draft is kept.")
            return
        self._all_notes = [item for item in self._all_notes if item.entry_id != note.entry_id]
        self._show_note(None)
        self._apply_filters()
        self._status_label.setText("Note deleted.")

    # ------------------------------------------------------------------
    def _on_new_note(self):
        """Open a small input dialog to bootstrap a new note."""
        from PyQt6.QtWidgets import QInputDialog
        import uuid

        if not self._confirm_leave():
            return

        title, ok = QInputDialog.getText(
            self, "New Note", "Entry title (mod name):"
        )
        if not ok or not title.strip():
            return

        # Pick the current type filter or default to "other"
        type_text   = self._type_combo.currentText()
        mod_type    = self._TYPE_MAP.get(type_text) or "other"

        try:
            from src.core.mod_notes import upsert_note
            note = upsert_note(
                self._config,
                entry_id    = "personal_" + uuid.uuid4().hex,
                entry_title = title.strip(),
                mod_type    = mod_type,
            )
        except Exception as exc:
            logger.warning("Could not create mod note: %s", exc)
            QMessageBox.critical(self, "Error", str(exc))
            return

        self._all_notes.insert(0, note)
        self._show_note(note)
        self._clear_filters()
        self._text_edit.setFocus()
        self._status_label.setText("New standalone note created. Existing catalogue notes are unchanged.")

    # ------------------------------------------------------------------
    def _on_clear(self):
        reply = QMessageBox.question(
            self,
            "Clear All Notes",
            "Delete ALL notes?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from src.core.mod_notes import clear_notes
            count = clear_notes(self._config)
        except Exception as exc:
            logger.warning("Could not clear mod notes: %s", exc)
            self._status_label.setText(f"Could not clear notes: {exc}\nYour draft is kept.")
            return
        self._all_notes = []
        self._show_note(None)
        self._apply_filters()
        self._status_label.setText(f"Removed {count} note(s).")

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
            logger.warning("Could not export mod notes CSV to %s: %s", path, exc)
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "✅ Export Complete",
            f"All saved notes exported to:\n{result}\n\nUnsaved drafts are not included.",
        )


# ===========================================================================
# Load Order Dialog
# ===========================================================================

class LoadOrderDialog(QDialog):
    """Dialog to manage the load order of mods for a specific game serial.

    Mods are displayed in order from lowest priority (top) to highest (bottom).
    Drag-to-reorder is emulated via Up / Down / Top / Bottom buttons.
    """

    def __init__(self, serial: str, db, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Load Order — {serial}")
        self.resize(540, 480)
        self._serial = serial
        self._db = db
        self._config = config

        from src.core.config_manager import LOAD_ORDER_FILE
        from src.core.load_order_manager import LoadOrderManager
        self._lom = LoadOrderManager(str(LOAD_ORDER_FILE))

        self._build()
        self._populate()

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Info label
        info = QLabel(
            "Mods listed <b>lower</b> have <b>higher priority</b> — they override "
            "textures or patches from mods above them.  "
            "Drag or use the buttons to reorder."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9090c0; font-size: 11px;")
        root.addWidget(info)

        # List widget
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setAlternatingRowColors(True)
        self._list.setStyleSheet(
            "QListWidget { background: #0d0d1a; color: #d0d0f0; font-size: 12px; }"
            "QListWidget::item:selected { background: #1a2a4a; }"
            "QListWidget::item:alternate { background: #0f0f22; }"
        )
        root.addWidget(self._list, 1)

        # Buttons row
        btn_row = QHBoxLayout()

        self._top_btn = QPushButton("⏫ Top")
        self._up_btn = QPushButton("↑ Up")
        self._down_btn = QPushButton("↓ Down")
        self._bottom_btn = QPushButton("⏬ Bottom")
        for b in (self._top_btn, self._up_btn, self._down_btn, self._bottom_btn):
            b.setFixedHeight(28)
            btn_row.addWidget(b)

        btn_row.addStretch()

        reset_btn = QPushButton("↺ Reset")
        reset_btn.setToolTip("Reset to alphabetical order")
        reset_btn.setFixedHeight(28)
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        root.addLayout(btn_row)

        self._top_btn.clicked.connect(self._on_top)
        self._up_btn.clicked.connect(self._on_up)
        self._down_btn.clicked.connect(self._on_down)
        self._bottom_btn.clicked.connect(self._on_bottom)

        # Dialog buttons
        from PyQt6.QtWidgets import QDialogButtonBox
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._save_and_accept)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)

    def _populate(self):
        from PyQt6.QtWidgets import QListWidgetItem
        from src.models.mod import ModType

        all_mods = self._db.all()
        serial = self._serial.upper()
        game_mods = {
            m.id: m for m in all_mods
            if m.game_id and m.game_id.upper() == serial
            and m.mod_type in (ModType.TEXTURE_PACK, ModType.PNACH, ModType.CHEAT)
        }

        # Build display order: saved order first, then any new mods appended
        saved_order = self._lom.get_order(self._serial)
        ordered_ids = [mid for mid in saved_order if mid in game_mods]
        remaining = [mid for mid in game_mods if mid not in set(ordered_ids)]
        ordered_ids.extend(sorted(remaining, key=lambda mid: game_mods[mid].name or ""))

        self._list.clear()
        for i, mid in enumerate(ordered_ids):
            mod = game_mods[mid]
            label = f"{i + 1}.  {mod.name or mod.id}  [{mod.mod_type.value}]"
            item = QListWidgetItem(label)
            item.setData(256, mid)  # store mod id in UserRole
            self._list.addItem(item)

        if self._list.count() == 0:
            placeholder = QListWidgetItem(
                "(No texture pack, PNACH, or cheat mods installed for this game)"
            )
            placeholder.setFlags(placeholder.flags() & ~2)  # not selectable
            placeholder.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#505070"))
            self._list.addItem(placeholder)

    def _current_row(self) -> int:
        return self._list.currentRow()

    def _on_top(self):
        row = self._current_row()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(0, item)
            self._list.setCurrentRow(0)
            self._renumber()

    def _on_up(self):
        row = self._current_row()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)
            self._renumber()

    def _on_down(self):
        row = self._current_row()
        if row >= 0 and row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)
            self._renumber()

    def _on_bottom(self):
        row = self._current_row()
        if row >= 0 and row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.addItem(item)
            self._list.setCurrentRow(self._list.count() - 1)
            self._renumber()

    def _on_reset(self):
        items = [self._list.item(i) for i in range(self._list.count())]
        items.sort(key=lambda it: (it.data(256) or ""))
        self._list.clear()
        for item in items:
            self._list.addItem(item)
        self._renumber()

    def _renumber(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            mid = item.data(256)
            if not mid:
                continue
            # Rebuild label preserving [type] suffix
            text = item.text()
            suffix = text.split("[")[-1].rstrip("]") if "[" in text else ""
            parts = text.split(".", 1)
            name_part = parts[1].strip().rsplit("[", 1)[0].strip() if len(parts) > 1 else text
            item.setText(f"{i + 1}.  {name_part}  [{suffix}]" if suffix else f"{i + 1}.  {name_part}")

    def _save_and_accept(self):
        order = []
        for i in range(self._list.count()):
            mid = self._list.item(i).data(256)
            if mid:
                order.append(mid)
        self._lom.set_order(self._serial, order)
        try:
            self._lom.save()
        except Exception as exc:
            logger.warning("Could not save load order for %s: %s", self._serial, exc)
            QMessageBox.critical(self, "Error", str(exc))
            return
        self.accept()


# ===========================================================================
# Mod Profiles Dialog
# ===========================================================================

class ModProfilesDialog(QDialog):
    """Dialog for managing named mod profiles.

    Profiles let users save named configurations of enabled mods and
    instantly switch between them (e.g. "Vanilla+", "HD Graphics", etc.).

    The last-used profile is highlighted. Applying uses the normal mod
    enable/disable workflow, including configured deployment destinations.
    """

    # Emitted when a profile is applied so the caller can refresh its view
    profile_applied = pyqtSignal(str)  # emits profile name

    def __init__(self, db, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mod Profiles")
        self.resize(580, 520)
        self._db = db
        self._config = config
        self._selection = ""

        from src.core.config_manager import PROFILES_FILE
        from src.core.mod_profile import ModProfileManager
        self._pm = ModProfileManager(str(PROFILES_FILE))

        self._build()
        self._refresh()

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Header
        header = QLabel(
            "Save your current mod configuration as a named profile, or switch "
            "between saved profiles. Applying changes enabled mods across the whole "
            "library, not just the current game. Priorities are unchanged; "
            "live memory-card files are never copied or removed."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #9090c0; font-size: 11px;")
        root.addWidget(header)

        # Splitter: left = profile list, right = detail
        from PyQt6.QtWidgets import QListWidget, QTextEdit
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)

        list_lbl = QLabel("Saved Profiles")
        list_lbl.setStyleSheet("font-weight:bold; color:#8090c0; font-size:12px;")
        left_lay.addWidget(list_lbl)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search profiles…")
        self._search_edit.setAccessibleName("Search profiles")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda *_: self._refresh())
        left_lay.addWidget(self._search_edit)
        self._count_lbl = QLabel()
        left_lay.addWidget(self._count_lbl)
        self._profile_list = QListWidget()
        self._profile_list.setMinimumWidth(180)
        self._profile_list.setWordWrap(True)
        self._profile_list.currentRowChanged.connect(self._on_selection_changed)
        self._profile_list.setStyleSheet(
            "QListWidget { background:#0d0d1a; color:#d0d0f0; font-size:12px; }"
            "QListWidget::item:selected { background:#1a2a4a; }"
        )
        left_lay.addWidget(self._profile_list, 1)

        splitter.addWidget(left)

        # Right panel: detail view
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)
        right_lay.setSpacing(6)

        detail_lbl = QLabel("Profile Details")
        detail_lbl.setStyleSheet("font-weight:bold; color:#8090c0; font-size:12px;")
        right_lay.addWidget(detail_lbl)

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            "background:#0d0d1a; color:#c0c0e0; font-size:11px; border:none;"
        )
        right_lay.addWidget(self._detail_text, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

        # Action buttons row
        act_row = QHBoxLayout()

        self._save_btn = QPushButton("💾 Save Current State")
        self._save_btn.setToolTip(
            "Snapshot the current enabled/disabled state of all mods into a new profile"
        )
        self._save_btn.clicked.connect(self._on_save_as)

        self._apply_btn = QPushButton("✅ Apply Profile")
        self._apply_btn.setToolTip(
            "Enable/disable mods to match the selected profile"
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)

        self._rename_btn = QPushButton("✏ Rename")
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._on_rename)

        self._dup_btn = QPushButton("📋 Duplicate")
        self._dup_btn.setEnabled(False)
        self._dup_btn.clicked.connect(self._on_duplicate)

        self._del_btn = QPushButton("🗑 Delete")
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet("color:#d06060;")
        self._del_btn.clicked.connect(self._on_delete)

        for b in (self._save_btn, self._apply_btn):
            b.setFixedHeight(28)
            act_row.addWidget(b)

        root.addLayout(act_row)
        manage_row = QHBoxLayout()
        for b in (self._rename_btn, self._dup_btn, self._del_btn):
            manage_row.addWidget(b)
        root.addLayout(manage_row)
        self._status_lbl = QLabel()
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._status_lbl)

        # Close button
        from PyQt6.QtWidgets import QDialogButtonBox
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bbox.rejected.connect(self.accept)
        root.addWidget(bbox)

    # ------------------------------------------------------------------
    def _refresh(self, selected=None):
        if selected is not None:
            self._selection = selected
            self._search_edit.blockSignals(True)
            self._search_edit.clear()
            self._search_edit.blockSignals(False)
        wanted = self._selection or self._pm.get_active_name()
        terms = self._search_edit.text().casefold().split()
        names = self._pm.list_profiles()
        visible = [
            name for name in names if all(
                term in f"{name} {self._pm.get_profile(name).description}".casefold()
                for term in terms
            )
        ]
        self._profile_list.blockSignals(True)
        self._profile_list.clear()
        active = self._pm.get_active_name()
        for name in visible:
            label = f"{'★ ' if name == active else ''}{name}"
            item = QListWidgetItem(label)
            item.setData(256, name)
            if name == active:
                from PyQt6.QtGui import QColor, QFont
                item.setForeground(QColor("#60d060"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._profile_list.addItem(item)
        if visible:
            self._profile_list.setCurrentRow(visible.index(wanted) if wanted in visible else 0)
        self._profile_list.blockSignals(False)
        self._count_lbl.setText(f"Showing {len(visible)} of {len(names)} profiles")
        self._on_selection_changed(self._profile_list.currentRow(), remember=False)

    def _profile_preview(self, profile):
        mods = {mod.id: mod for mod in self._db.all()}
        enabled = set(profile.enabled_mods)
        available = enabled.intersection(mods)
        missing = enabled.difference(mods)
        to_enable = [mod for mod in mods.values() if mod.id in enabled and not mod.enabled]
        to_disable = [mod for mod in mods.values() if mod.id not in enabled and mod.enabled]
        return mods, available, missing, to_enable, to_disable

    def _persist_profiles(self, operation, selected, message):
        candidate = deepcopy(self._pm)
        try:
            operation(candidate)
            candidate.save()
        except Exception as exc:
            logger.warning("Could not update mod profiles: %s", exc)
            self._status_lbl.setText("Could not save profiles. No profile changes were committed.")
            QMessageBox.critical(self, "Profile Save Failed", f"<p>{escape(str(exc))}</p>")
            return False
        self._pm = candidate
        self._refresh(selected)
        self._status_lbl.setText(message)
        return True

    def _selected_profile(self) -> str:
        item = self._profile_list.currentItem()
        if item:
            return item.data(256) or ""
        return ""

    def _on_selection_changed(self, _row: int, remember=True):
        name = self._selected_profile()
        if name and remember:
            self._selection = name
        has_sel = bool(name)
        self._apply_btn.setEnabled(has_sel)
        self._rename_btn.setEnabled(has_sel)
        self._dup_btn.setEnabled(has_sel)
        self._del_btn.setEnabled(has_sel)

        if name:
            profile = self._pm.get_profile(name)
            if profile:
                mods, available, missing, to_enable, to_disable = self._profile_preview(profile)
                lines = [
                    name + ("  ★ last used" if name == self._pm.get_active_name() else ""),
                ]
                if profile.description:
                    lines.append(profile.description)
                lines.extend((
                    f"\nSaved: {len(available)} installed, {len(missing)} missing.",
                    f"Changes: enable {len(to_enable)}, disable {len(to_disable)}.",
                    "Scope: all installed mods. Priorities are unchanged.",
                    "Save-file flags only: live memory cards are never copied or removed.",
                ))
                if not to_enable and not to_disable:
                    lines.append("Enabled states already match this profile.")
                if self._config is None:
                    lines.append("No configuration supplied: database flags only, no deployment.")
                lines.append("\nEnabled mods in this profile:")
                for mid in dict.fromkeys(profile.enabled_mods):
                    lines.append(f"• {mods[mid].name or mid}" if mid in mods else f"• Missing: {mid}")
                self._detail_text.setPlainText("\n".join(lines))
            else:
                self._detail_text.setPlainText("")
        else:
            self._detail_text.setPlainText(
                "No profiles match. Clear the search to see more."
                if self._pm.list_profiles()
                else "No saved profiles yet. Use Save Current State to create one."
            )

    def _on_save_as(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:",
            text=self._pm.get_active_name() or "My Profile"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = self._pm.get_profile(name)
        if existing:
            reply = QMessageBox.question(
                self, "Overwrite Profile",
                f"<p>Replace the saved enabled-mod list for '{escape(name)}' with the current state?</p>",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        desc, ok2 = QInputDialog.getText(
            self, "Description", "Short description (optional):",
            text=existing.description if existing else "",
        )
        if not ok2:
            return

        # Snapshot the current mod enable state
        all_mods = self._db.all()
        enabled_ids = [m.id for m in all_mods if m.enabled]

        def update(manager):
            if manager.get_profile(name):
                profile = manager.get_profile(name)
                profile.enabled_mods = enabled_ids
                profile.description = desc.strip()
            else:
                manager.create_profile(name, description=desc.strip(), enabled_mods=enabled_ids)
            manager.set_active(name)
        self._persist_profiles(update, name, f"Saved profile '{name}'.")

    def _on_apply(self):
        name = self._selected_profile()
        if not name:
            return
        profile = self._pm.get_profile(name)
        if not profile:
            return

        mods, available, missing, to_enable, to_disable = self._profile_preview(profile)
        reply = QMessageBox.question(
            self,
            "Apply Profile",
            f"<p>Apply profile '{escape(name)}' across the whole library?</p>"
            f"<p>Enable {len(to_enable)} and disable {len(to_disable)} mod(s).<br>"
            f"{len(missing)} saved mod(s) are missing and will be skipped.</p>"
            + ("Configured PCSX2 folders will be updated. Priorities are unchanged. "
               "Live memory cards are never copied or removed."
               if self._config is not None else "Database flags only; no deployment configuration supplied."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.mod_manager import ModManager
        manager = ModManager(self._db)
        warnings = []
        try:
            _count, warnings = manager.set_enabled_many(
                {mid: mid in available for mid in mods}, self._config,
            )
        except Exception as exc:
            logger.warning("Could not apply profile %s: %s", name, exc)
            self._status_lbl.setText("Profile application stopped. Some mods may have changed; review their state.")
            QMessageBox.critical(self, "Profile Partially Applied", f"<p>{escape(str(exc))}</p>")
            self._refresh(name)
            self.profile_applied.emit(name)
            return
        saved = self._persist_profiles(
            lambda pm: pm.set_active(name), name,
            f"Profile '{name}': {len(available)} installed mods enabled; {len(missing)} missing.",
        )
        self.profile_applied.emit(name)
        if not saved:
            self._refresh(name)
            self._status_lbl.setText("Mod states changed, but the last-used profile could not be saved.")
        if warnings:
            self._status_lbl.setText("Mod states changed with deployment warnings. Check PCSX2 paths and files.")
            detail = "<br>".join(escape(notice) for notice in dict.fromkeys(warnings))
            QMessageBox.warning(self, "Profile Deployment Warnings", f"<p>{detail}</p>")

    def _on_rename(self):
        old = self._selected_profile()
        if not old:
            return
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "New name:", text=old
        )
        if not ok or not new_name.strip() or new_name.strip() == old:
            return
        def rename(manager):
            if not manager.rename_profile(old, new_name.strip()):
                raise ValueError("That profile name is already in use.")
        self._persist_profiles(rename, new_name.strip(), "Profile renamed.")

    def _on_duplicate(self):
        src = self._selected_profile()
        if not src:
            return
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Duplicate Profile", "New profile name:", text=f"{src} (copy)"
        )
        if not ok or not new_name.strip():
            return
        def duplicate(manager):
            if manager.duplicate_profile(src, new_name.strip()) is None:
                raise ValueError("That profile name is already in use.")
        self._persist_profiles(duplicate, new_name.strip(), "Profile duplicated.")

    def _on_delete(self):
        name = self._selected_profile()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"<p>Delete profile '{escape(name)}'?</p>"
            "This cannot be undone. Installed mods are not removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._persist_profiles(lambda pm: pm.delete_profile(name), "", "Profile deleted. Mod states are unchanged.")
