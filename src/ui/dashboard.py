"""Dashboard panel — overview and quick stats."""

import time
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

PATREON_URL = "https://www.patreon.com/c/DeadOnTheInside"


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
            "PNACH / Cheats": self.config.pnach_path,
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

        # ---- Recently Added ----
        recent_all = sorted(self.db.all(), key=lambda m: getattr(m, "installed_at", 0), reverse=True)
        recent = recent_all[:6]
        if recent:
            recent_frame = QFrame()
            recent_frame.setObjectName("card")
            recent_layout = QVBoxLayout(recent_frame)
            recent_layout.setContentsMargins(16, 12, 16, 12)
            recent_layout.setSpacing(6)

            recent_title = QLabel("🕐  Recently Added")
            recent_title.setStyleSheet("font-weight: bold; color: #b0b0d0; font-size: 14px;")
            recent_layout.addWidget(recent_title)

            _type_icons = {
                "texture_pack": "🎨",
                "pnach": "🔧",
                "cover_art": "🖼️",
                "save_file": "💾",
                "cheat": "⚡",
            }

            for mod in recent:
                row = QHBoxLayout()
                type_icon = _type_icons.get(mod.mod_type.value, "📦")
                icon_lbl = QLabel(type_icon)
                icon_lbl.setFixedWidth(24)
                icon_lbl.setStyleSheet("font-size: 14px;")
                row.addWidget(icon_lbl)

                name_lbl = QLabel(mod.name)
                name_lbl.setStyleSheet("color: #d0d0e8; font-size: 12px;")
                row.addWidget(name_lbl, 1)

                if mod.author and mod.author != "Unknown":
                    auth_lbl = QLabel(f"by {mod.author}")
                    auth_lbl.setStyleSheet("color: #7070a0; font-size: 11px;")
                    row.addWidget(auth_lbl)

                ts = getattr(mod, "installed_at", 0)
                if ts:
                    from datetime import datetime
                    try:
                        dt = datetime.fromtimestamp(ts)
                        time_str = dt.strftime("%b %d, %H:%M")
                    except Exception:
                        time_str = ""
                    if time_str:
                        time_lbl = QLabel(time_str)
                        time_lbl.setStyleSheet("color: #50507a; font-size: 10px;")
                        row.addWidget(time_lbl)

                enabled_dot = QLabel("●" if mod.enabled else "○")
                enabled_dot.setStyleSheet(
                    "color: #22c870; font-size: 10px;" if mod.enabled else "color: #555570; font-size: 10px;"
                )
                enabled_dot.setToolTip("Enabled" if mod.enabled else "Disabled")
                row.addWidget(enabled_dot)

                recent_layout.addLayout(row)

            content.addWidget(recent_frame)

        # ---- Patreon / About banner ----
        about_frame = QFrame()
        about_frame.setObjectName("card")
        about_frame.setStyleSheet(
            "QFrame#card { border: 1px solid #f96854; background: #1e1010; }"
        )
        about_layout = QHBoxLayout(about_frame)
        about_layout.setContentsMargins(16, 14, 16, 14)
        about_layout.setSpacing(16)

        heart_lbl = QLabel("❤")
        heart_lbl.setStyleSheet("font-size: 36px;")
        about_layout.addWidget(heart_lbl)

        msg_col = QVBoxLayout()
        msg_col.setSpacing(4)
        msg_title = QLabel("<b>PS2 Mod Manager is free!</b>")
        msg_title.setStyleSheet("font-size: 14px; color: #f96854;")
        msg_col.addWidget(msg_title)
        msg_sub = QLabel(
            "If you enjoy this tool, please consider supporting the developer on Patreon.\n"
            "Your support helps keep the project alive and funded!"
        )
        msg_sub.setStyleSheet("color: #c0a0a0; font-size: 12px;")
        msg_sub.setWordWrap(True)
        msg_col.addWidget(msg_sub)
        about_layout.addLayout(msg_col, 1)

        patreon_btn = QPushButton("❤  Support on Patreon")
        patreon_btn.setObjectName("patreon_btn")
        patreon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        patreon_btn.setFixedWidth(180)
        patreon_btn.clicked.connect(self._open_patreon)
        about_layout.addWidget(patreon_btn)

        content.addWidget(about_frame)
        content.addStretch()

    def refresh(self):
        """Rebuild the dashboard with fresh data."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._build()

    def _open_patreon(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(PATREON_URL))
