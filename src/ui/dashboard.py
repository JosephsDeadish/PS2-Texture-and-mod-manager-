"""Dashboard panel — overview and quick stats."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.mod_manager import ModDatabase, ModManager
from src.models.mod import AppConfig, ModType
from src.ui.base_panel import BasePanel


class StatCard(QFrame):
    """A numeric stat card shown on the dashboard."""

    def __init__(self, icon: str, label: str, value: str, color: str = "#e94560"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 32px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        val_lbl = QLabel(value)
        val_lbl.setObjectName("val_lbl")
        val_lbl.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(val_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #7070a0; font-size: 12px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        self._val_lbl = val_lbl

    def set_value(self, value: str):
        self._val_lbl.setText(value)


class DashboardPanel(BasePanel):
    """Main dashboard with stats and recent activity."""

    def __init__(self, db: ModDatabase, config: AppConfig, parent=None):
        super().__init__("🏠  Dashboard", parent=parent)
        self.db = db
        self.config = config
        self._build()

    def _build(self):
        content = self._content_layout

        # ---- Welcome message ----
        welcome = QLabel("Welcome to PS2 Mod Manager")
        welcome.setObjectName("section_title")
        content.addWidget(welcome)

        sub = QLabel("Manage your PCSX2 texture packs, patches, saves, and more.")
        sub.setObjectName("section_subtitle")
        content.addWidget(sub)

        # ---- Stats row ----
        stats_scroll = QScrollArea()
        stats_scroll.setWidgetResizable(True)
        stats_scroll.setMaximumHeight(160)
        stats_scroll.setFrameShape(QFrame.Shape.NoFrame)
        stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        stats_container = QWidget()
        stats_row = QHBoxLayout(stats_container)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)

        all_mods = self.db.all()
        enabled_mods = [m for m in all_mods if m.enabled]
        conflicts = ModManager(self.db).detect_conflicts()

        self._card_total = StatCard("📦", "Total Mods", str(len(all_mods)), "#6080d0")
        self._card_enabled = StatCard("✅", "Enabled", str(len(enabled_mods)), "#22c870")
        self._card_texture = StatCard(
            "🎨", "Texture Packs",
            str(len(self.db.by_type(ModType.TEXTURE_PACK))), "#e94560"
        )
        self._card_pnach = StatCard(
            "🔧", "PNACH Files",
            str(len(self.db.by_type(ModType.PNACH))), "#e09030"
        )
        self._card_saves = StatCard(
            "💾", "Save Files",
            str(len(self.db.by_type(ModType.SAVE_FILE))), "#30a0c0"
        )
        self._card_conflicts = StatCard(
            "⚠", "Conflicts",
            str(len(conflicts)),
            "#e94560" if conflicts else "#22c870"
        )

        for card in (
            self._card_total, self._card_enabled,
            self._card_texture, self._card_pnach,
            self._card_saves, self._card_conflicts,
        ):
            card.setMinimumWidth(130)
            stats_row.addWidget(card)

        stats_row.addStretch()
        stats_scroll.setWidget(stats_container)
        content.addWidget(stats_scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        content.addWidget(sep)

        # ---- Conflict warning ----
        if conflicts:
            warn_frame = QFrame()
            warn_frame.setObjectName("card")
            warn_frame.setStyleSheet(
                "QFrame#card { border: 1px solid #e94560; background: #1e0a0a; }"
            )
            warn_layout = QHBoxLayout(warn_frame)
            warn_layout.setContentsMargins(16, 12, 16, 12)

            icon = QLabel("⚠")
            icon.setStyleSheet("font-size: 28px;")
            warn_layout.addWidget(icon)

            msg = QLabel(
                f"<b>{len(conflicts)} mod conflict(s) detected.</b><br>"
                "Some mods share the same files. Go to the relevant section to resolve them."
            )
            msg.setStyleSheet("color: #ff8080;")
            msg.setWordWrap(True)
            warn_layout.addWidget(msg, 1)
            content.addWidget(warn_frame)

        # ---- PCSX2 config status ----
        cfg_frame = QFrame()
        cfg_frame.setObjectName("card")
        cfg_layout = QVBoxLayout(cfg_frame)
        cfg_layout.setContentsMargins(16, 12, 16, 12)
        cfg_layout.setSpacing(6)

        cfg_title = QLabel("⚙  PCSX2 Configuration")
        cfg_title.setStyleSheet("font-weight: bold; color: #b0b0d0; font-size: 14px;")
        cfg_layout.addWidget(cfg_title)

        paths = {
            "PCSX2 Root": self.config.pcsx2_path,
            "Textures": self.config.textures_path,
            "PNACH": self.config.pnach_path,
            "Cover Art": self.config.cover_art_path,
            "Memory Cards": self.config.memcards_path,
        }

        for key, val in paths.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{key}:"))
            status = "✅" if val else "❌ Not configured"
            disp = QLabel(f"{status}  {val}" if val else status)
            disp.setStyleSheet(
                "color: #22c870;" if val else "color: #e94560;"
            )
            disp.setWordWrap(True)
            row.addWidget(disp, 1)
            cfg_layout.addLayout(row)

        content.addWidget(cfg_frame)
        content.addStretch()

    def refresh(self):
        """Rebuild the dashboard with fresh data."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._build()
