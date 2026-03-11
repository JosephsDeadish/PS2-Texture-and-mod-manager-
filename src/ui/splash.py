"""Animated startup splash screen for PS2 Mod Manager.

Displays an animated PS2 controller icon (pulsing glow ring + rotating
disc) with loading progress messages while the application initialises.
Uses only Qt primitives — no extra dependencies required.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import (
    QObject,
    QPropertyAnimation,
    QRect,
    Qt,
    QThread,
    QTimer,
    QVariantAnimation,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QLabel, QSplashScreen, QWidget


# ---------------------------------------------------------------------------
# Animated splash widget
# ---------------------------------------------------------------------------

class SplashWidget(QWidget):
    """
    A frameless window used as the splash screen.

    Draws:
    - Dark rounded rectangle background
    - PS2 controller icon (from assets if available, else emoji fallback)
    - Animated pulsing glow ring around the icon
    - Rotating accent arc
    - App title text
    - Scrolling status message at the bottom
    """

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 320)

        self._angle: float = 0.0       # rotating arc angle
        self._glow_alpha: int = 60     # pulsing glow opacity
        self._glow_dir: int = 1        # +1 growing, -1 shrinking
        self._message: str = "Starting up…"
        self._progress: float = 0.0    # 0.0 – 1.0

        # Load controller icon (may be unavailable during first install)
        self._icon_pix: Optional[QPixmap] = None
        try:
            from src.core.assets import icon_path
            p = icon_path(128)
            import os
            if os.path.exists(p):
                self._icon_pix = QPixmap(p).scaled(
                    96, 96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception:
            pass

        # Animation timer — 30 fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        # Centre on primary screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            self.move(
                sg.center().x() - self.width() // 2,
                sg.center().y() - self.height() // 2,
            )

    # ------------------------------------------------------------------

    def set_message(self, msg: str, progress: float = -1.0):
        self._message = msg
        if progress >= 0:
            self._progress = max(0.0, min(1.0, progress))
        self.update()

    # ------------------------------------------------------------------

    def _tick(self):
        self._angle = (self._angle + 3.0) % 360.0

        self._glow_alpha += 4 * self._glow_dir
        if self._glow_alpha >= 140:
            self._glow_dir = -1
        elif self._glow_alpha <= 40:
            self._glow_dir = 1

        self.update()

    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()

        # ── Background ─────────────────────────────────────────────────
        bg_rect = QRect(4, 4, W - 8, H - 8)
        painter.setBrush(QBrush(QColor(15, 15, 30)))
        painter.setPen(QPen(QColor(30, 40, 80), 2))
        painter.drawRoundedRect(bg_rect, 20, 20)

        # ── Subtle top gradient overlay ─────────────────────────────────
        grad = QRadialGradient(W / 2, 60, 200)
        grad.setColorAt(0, QColor(14, 52, 96, 80))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bg_rect, 20, 20)

        cx, cy = W // 2, H // 2 - 30   # icon centre

        # ── Pulsing outer glow ring ─────────────────────────────────────
        glow_color = QColor(233, 69, 96, self._glow_alpha)
        for i in range(3, 0, -1):
            r = 64 + i * 12
            painter.setPen(QPen(glow_color, max(1, 3 - i + 1)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # ── Rotating accent arc ─────────────────────────────────────────
        arc_pen = QPen(QColor(233, 69, 96, 200), 3)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r_arc = 60
        rect_arc = QRect(cx - r_arc, cy - r_arc, r_arc * 2, r_arc * 2)
        painter.drawArc(rect_arc, int(-self._angle * 16), 120 * 16)
        painter.drawArc(rect_arc, int((-self._angle + 180) * 16), 60 * 16)

        # ── Icon or fallback emoji ──────────────────────────────────────
        if self._icon_pix:
            iw, ih = self._icon_pix.width(), self._icon_pix.height()
            painter.drawPixmap(cx - iw // 2, cy - ih // 2, self._icon_pix)
        else:
            font = QFont("Segoe UI", 52)
            painter.setFont(font)
            painter.setPen(QPen(QColor(233, 69, 96)))
            painter.drawText(
                QRect(cx - 40, cy - 40, 80, 80),
                Qt.AlignmentFlag.AlignCenter,
                "🎮",
            )

        # ── App title ──────────────────────────────────────────────────
        title_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(
            QRect(0, cy + 72, W, 36),
            Qt.AlignmentFlag.AlignCenter,
            "PS2 Mod Manager",
        )

        sub_font = QFont("Segoe UI", 10)
        painter.setFont(sub_font)
        painter.setPen(QPen(QColor(100, 100, 160)))
        painter.drawText(
            QRect(0, cy + 108, W, 24),
            Qt.AlignmentFlag.AlignCenter,
            "v1.0.0",
        )

        # ── Status message ─────────────────────────────────────────────
        msg_font = QFont("Segoe UI", 9)
        painter.setFont(msg_font)
        painter.setPen(QPen(QColor(144, 144, 180)))
        painter.drawText(
            QRect(20, H - 52, W - 40, 20),
            Qt.AlignmentFlag.AlignCenter,
            self._message,
        )

        # ── Progress bar ───────────────────────────────────────────────
        bar_rect = QRect(40, H - 30, W - 80, 6)
        painter.setBrush(QBrush(QColor(20, 25, 50)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bar_rect, 3, 3)

        if self._progress > 0:
            fill_w = int(bar_rect.width() * self._progress)
            fill_rect = QRect(bar_rect.x(), bar_rect.y(), fill_w, bar_rect.height())
            painter.setBrush(QBrush(QColor(233, 69, 96)))
            painter.drawRoundedRect(fill_rect, 3, 3)

        painter.end()


# ---------------------------------------------------------------------------
# Public API used by main.py
# ---------------------------------------------------------------------------

def create_splash() -> SplashWidget:
    """Create and show the splash widget. Returns the widget."""
    splash = SplashWidget()
    splash.show()
    QApplication.processEvents()
    return splash


def destroy_splash(splash: SplashWidget):
    """Fade out and destroy the splash widget."""
    if splash is None:
        return
    # Quick fade: just close immediately (animation runs in background)
    splash.close()
    splash.deleteLater()
