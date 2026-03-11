"""Initial Setup Wizard for PS2 Mod Manager."""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QMessageBox,
)

from src.models.mod import AppConfig
from src.core.config_manager import detect_pcsx2_paths, save_config
from src.ui.widgets import PathChooser


class SetupWizard(QDialog):
    """
    Multi-page setup wizard shown on first launch.
    Guides the user through selecting PCSX2 paths.
    """

    setup_complete = pyqtSignal(AppConfig)

    _PAGES = ["Welcome", "PCSX2 Location", "Advanced Paths", "Mod Storage", "Done"]

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("PS2 Mod Manager — Setup")
        self.setMinimumSize(680, 520)
        self.setModal(True)
        self._page_index = 0
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Title bar ----
        title_bar = QFrame()
        title_bar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #0f3460, stop:1 #e94560);"
            "min-height: 80px; max-height: 80px;"
        )
        tb_layout = QVBoxLayout(title_bar)
        tb_layout.setContentsMargins(28, 12, 28, 12)

        title_lbl = QLabel("⚙️  PS2 Mod Manager Setup")
        title_lbl.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffffff;")
        tb_layout.addWidget(title_lbl)

        self._step_lbl = QLabel(self._step_text())
        self._step_lbl.setStyleSheet("color: #c0c0e0; font-size: 12px;")
        tb_layout.addWidget(self._step_lbl)

        root.addWidget(title_bar)

        # ---- Page stack ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_welcome())
        self._stack.addWidget(self._page_pcsx2())
        self._stack.addWidget(self._page_advanced())
        self._stack.addWidget(self._page_storage())
        self._stack.addWidget(self._page_done())
        root.addWidget(self._stack, 1)

        # ---- Navigation ----
        nav_frame = QFrame()
        nav_frame.setStyleSheet("background: #16213e; border-top: 1px solid #0f3460;")
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setContentsMargins(20, 12, 20, 12)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._go_back)
        nav_layout.addWidget(self._back_btn)
        nav_layout.addStretch()

        self._skip_btn = QPushButton("Skip Setup")
        self._skip_btn.setStyleSheet("color: #7070a0;")
        self._skip_btn.clicked.connect(self._skip)
        nav_layout.addWidget(self._skip_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("primary_btn")
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self._next_btn)

        root.addWidget(nav_frame)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(14)

        layout.addStretch()
        hero = QLabel("🎮")
        hero.setStyleSheet("font-size: 72px;")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hero)

        title = QLabel("Welcome to PS2 Mod Manager")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "This wizard will help you configure PS2 Mod Manager by locating your\n"
            "PCSX2 installation and setting up mod folders.\n\n"
            "You can re-run this wizard at any time from Settings."
        )
        desc.setStyleSheet("color: #9090b0; font-size: 14px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addStretch()

        return w

    def _page_pcsx2(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(14)

        layout.addWidget(_h("PCSX2 Installation"))
        layout.addWidget(_p(
            "Select your PCSX2 installation or config directory.\n"
            "PS2 Mod Manager will automatically detect sub-folders "
            "(textures, covers, memory cards, etc.)."
        ))

        self._pcsx2_chooser = PathChooser("PCSX2 Config Dir:", "e.g. ~/snap/pcsx2/current/.config/PCSX2")
        self._pcsx2_chooser.set_path(self.config.pcsx2_path)
        self._pcsx2_chooser.path_changed.connect(self._on_pcsx2_path_changed)
        layout.addWidget(self._pcsx2_chooser)

        auto_btn = QPushButton("🔍 Auto-detect PCSX2")
        auto_btn.clicked.connect(self._auto_detect)
        layout.addWidget(auto_btn)

        self._pcsx2_status = QLabel("")
        self._pcsx2_status.setWordWrap(True)
        layout.addWidget(self._pcsx2_status)

        layout.addStretch()
        return w

    def _page_advanced(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 24, 40, 20)
        layout.setSpacing(10)

        layout.addWidget(_h("PCSX2 Folder Paths"))
        layout.addWidget(_p(
            "These paths are auto-filled if you selected a PCSX2 directory.\n"
            "You can adjust them individually here."
        ))

        self._tex_chooser = PathChooser("Textures:", "textures folder")
        self._tex_chooser.set_path(self.config.textures_path)
        layout.addWidget(self._tex_chooser)

        self._pnach_chooser = PathChooser("PNACH/Patches:", "cheats/patches folder")
        self._pnach_chooser.set_path(self.config.pnach_path)
        layout.addWidget(self._pnach_chooser)

        self._covers_chooser = PathChooser("Cover Art:", "covers folder")
        self._covers_chooser.set_path(self.config.cover_art_path)
        layout.addWidget(self._covers_chooser)

        self._memcards_chooser = PathChooser("Memory Cards:", "memcards folder")
        self._memcards_chooser.set_path(self.config.memcards_path)
        layout.addWidget(self._memcards_chooser)

        self._cheats_chooser = PathChooser("Cheats/WS:", "cheats_ws folder")
        self._cheats_chooser.set_path(self.config.cheats_path)
        layout.addWidget(self._cheats_chooser)

        layout.addStretch()
        return w

    def _page_storage(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(14)

        layout.addWidget(_h("Mod Storage Location"))
        layout.addWidget(_p(
            "Choose where PS2 Mod Manager will store downloaded/imported mods.\n"
            "This is separate from PCSX2; only enabled mods are deployed."
        ))

        from src.core.config_manager import get_data_dir
        default_storage = str(get_data_dir() / "mods")

        self._storage_chooser = PathChooser("Mods Folder:", default_storage)
        self._storage_chooser.set_path(self.config.mods_storage_path or default_storage)
        layout.addWidget(self._storage_chooser)

        note = QLabel(
            "ℹ  Lots of mods can be stored here.\n"
            "Only mods you enable will actually be deployed to PCSX2."
        )
        note.setStyleSheet("color: #7070a0; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # ── Automatic mode ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        layout.addWidget(_h("Automatic Setup"))
        layout.addWidget(_p(
            "Check this option to let PS2 Mod Manager automatically create any\n"
            "missing PCSX2 sub-folders (textures/, covers/, cheats/, etc.) and\n"
            "deploy enabled mods whenever you toggle them on."
        ))

        self._auto_create_dirs_check = QCheckBox(
            "Create missing PCSX2 folders automatically"
        )
        self._auto_create_dirs_check.setChecked(False)
        layout.addWidget(self._auto_create_dirs_check)

        self._auto_deploy_check = QCheckBox(
            "Auto-deploy mods to PCSX2 when enabled/disabled"
        )
        self._auto_deploy_check.setChecked(self.config.auto_deploy)
        layout.addWidget(self._auto_deploy_check)

        layout.addStretch()
        return w

    def _page_done(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(14)

        layout.addStretch()
        hero = QLabel("✅")
        hero.setStyleSheet("font-size: 72px;")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hero)

        title = QLabel("Setup Complete!")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._done_summary = QLabel(
            "PS2 Mod Manager is ready to use.\n"
            "You can change these settings at any time from the Settings panel."
        )
        self._done_summary.setStyleSheet("color: #9090b0; font-size: 14px;")
        self._done_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_summary.setWordWrap(True)
        layout.addWidget(self._done_summary)
        layout.addStretch()

        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _step_text(self) -> str:
        total = len(self._PAGES)
        current = self._page_index + 1
        name = self._PAGES[self._page_index]
        return f"Step {current} of {total}  —  {name}"

    def _go_next(self):
        if self._page_index == len(self._PAGES) - 1:
            self._finish()
            return

        self._collect_current_page()
        self._page_index += 1
        self._stack.setCurrentIndex(self._page_index)
        self._step_lbl.setText(self._step_text())
        self._back_btn.setEnabled(self._page_index > 0)

        if self._page_index == len(self._PAGES) - 1:
            # Entering "Done" page — run automatic actions and update summary
            self._run_automatic_setup()
            self._next_btn.setText("Finish ✓")
            self._next_btn.setObjectName("success_btn")
            self._skip_btn.hide()
        else:
            self._next_btn.setText("Next →")

    def _go_back(self):
        if self._page_index > 0:
            self._page_index -= 1
            self._stack.setCurrentIndex(self._page_index)
            self._step_lbl.setText(self._step_text())
            self._back_btn.setEnabled(self._page_index > 0)
            self._next_btn.setText("Next →")
            self._next_btn.setObjectName("primary_btn")
            self._skip_btn.show()

    def _collect_current_page(self):
        """Persist values from the current page into self.config."""
        page = self._page_index
        if page == 1:
            self.config.pcsx2_path = self._pcsx2_chooser.get_path()
        elif page == 2:
            self.config.textures_path = self._tex_chooser.get_path()
            self.config.pnach_path = self._pnach_chooser.get_path()
            self.config.cover_art_path = self._covers_chooser.get_path()
            self.config.memcards_path = self._memcards_chooser.get_path()
            self.config.cheats_path = self._cheats_chooser.get_path()
        elif page == 3:
            self.config.mods_storage_path = self._storage_chooser.get_path()
            self.config.auto_deploy = self._auto_deploy_check.isChecked()

    def _run_automatic_setup(self):
        """
        If the user checked 'Create missing PCSX2 folders', scaffold the
        standard PCSX2 directory tree now.  Updates the Done-page summary.
        """
        summary_lines = []

        if (
            hasattr(self, "_auto_create_dirs_check")
            and self._auto_create_dirs_check.isChecked()
            and self.config.pcsx2_path
        ):
            try:
                from src.core.pcsx2_layout import create_pcsx2_directories
                created = create_pcsx2_directories(self.config.pcsx2_path)
                if created:
                    summary_lines.append(
                        f"📁 Created {len(created)} missing PCSX2 folder(s)."
                    )
                else:
                    summary_lines.append("📁 All PCSX2 folders already exist.")
            except Exception as exc:
                summary_lines.append(f"⚠️  Could not create folders: {exc}")

        if self.config.pcsx2_path:
            summary_lines.append(f"📂 PCSX2: {self.config.pcsx2_path}")
        if self.config.textures_path:
            summary_lines.append(f"🖼  Textures: {self.config.textures_path}")
        if self.config.pnach_path:
            summary_lines.append(f"📝 PNACH: {self.config.pnach_path}")
        if self.config.cover_art_path:
            summary_lines.append(f"🎨 Covers: {self.config.cover_art_path}")
        if self.config.auto_deploy:
            summary_lines.append("⚡ Auto-deploy: enabled")

        if summary_lines:
            self._done_summary.setText("\n".join(summary_lines))

    def _finish(self):
        self._collect_current_page()
        self.config.first_run = False
        save_config(self.config)
        self.setup_complete.emit(self.config)
        self.accept()

    def _skip(self):
        self.config.first_run = False
        save_config(self.config)
        self.setup_complete.emit(self.config)
        self.reject()

    # ------------------------------------------------------------------
    # Auto-detect
    # ------------------------------------------------------------------

    def _on_pcsx2_path_changed(self, path: str):
        if path:
            self._auto_fill_from_path(path)

    def _auto_detect(self):
        # Try the new comprehensive detector first
        try:
            from src.core.pcsx2_layout import auto_detect_pcsx2
            found = auto_detect_pcsx2()
            if found:
                self._pcsx2_chooser.set_path(found)
                self._auto_fill_from_path(found)
                self._pcsx2_status.setText(f"✅ Found: {found}")
                return
        except Exception:
            pass

        # Fallback to legacy candidate list
        candidates = [
            Path.home() / "snap" / "pcsx2" / "current" / ".config" / "PCSX2",
            Path.home() / ".config" / "PCSX2",
            Path.home() / "AppData" / "Roaming" / "PCSX2",
            Path("/Applications/PCSX2.app/Contents/Resources"),
        ]
        for candidate in candidates:
            if candidate.exists():
                self._pcsx2_chooser.set_path(str(candidate))
                self._auto_fill_from_path(str(candidate))
                self._pcsx2_status.setText(f"✅ Found: {candidate}")
                return
        self._pcsx2_status.setText(
            "❌ Could not auto-detect PCSX2. Please browse manually."
        )

    def _auto_fill_from_path(self, path: str):
        paths = detect_pcsx2_paths(path)
        self._tex_chooser.set_path(paths.get("textures_path", ""))
        self._pnach_chooser.set_path(paths.get("pnach_path", ""))
        self._covers_chooser.set_path(paths.get("cover_art_path", ""))
        self._memcards_chooser.set_path(paths.get("memcards_path", ""))
        self._cheats_chooser.set_path(paths.get("cheats_path", ""))
        # Store partial_textures_path in config immediately
        self.config.partial_textures_path = paths.get("partial_textures_path", "")


# ---------------------------------------------------------------------------
# Helper label factories
# ---------------------------------------------------------------------------

def _h(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
    return lbl


def _p(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #9090b0; font-size: 13px;")
    lbl.setWordWrap(True)
    return lbl

