"""GIF Maker panel — build animated GIFs from image sequences."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.ffmpeg_utils import ffmpeg_available
from src.core.gif_maker import create_gif
from src.models.mod import AppConfig
from src.ui.base_panel import BasePanel


class GifMakerPanel(BasePanel):
    """Panel for building animated GIFs from image frames."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__("🎞️  GIF Maker", "Create GIFs from image sequences", parent=parent)
        self.config = config
        self._build()

    def _build(self):
        content = self._content_layout

        info = QLabel(
            "Add frames, drag to reorder, choose a frame delay, and export a GIF."
        )
        info.setStyleSheet("color: #7070a0; font-size: 12px;")
        info.setWordWrap(True)
        content.addWidget(info)

        self._ffmpeg_status = QLabel("Checking FFmpeg status…")
        self._ffmpeg_status.setStyleSheet("color: #506090; font-size: 11px;")
        content.addWidget(self._ffmpeg_status)
        self._refresh_ffmpeg_status()

        list_frame = QFrame()
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)

        self._frame_list = QListWidget()
        self._frame_list.setAlternatingRowColors(True)
        self._frame_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._frame_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._frame_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._frame_list.setDropIndicatorShown(True)
        self._frame_list.setStyleSheet(
            "QListWidget { background: #0d0d1a; color: #d0d0f0; font-size: 12px; }"
            "QListWidget::item:selected { background: #1a2a4a; }"
            "QListWidget::item:alternate { background: #0f0f22; }"
        )
        model = self._frame_list.model()
        model.rowsMoved.connect(self._renumber_items)
        model.rowsInserted.connect(self._renumber_items)
        model.rowsRemoved.connect(self._renumber_items)
        list_layout.addWidget(self._frame_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ Add Images")
        add_btn.clicked.connect(self._add_images)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("🗑 Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("✖ Clear")
        clear_btn.clicked.connect(self._clear_frames)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        list_layout.addLayout(btn_row)

        content.addWidget(list_frame, 1)

        options_frame = QFrame()
        options_layout = QHBoxLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)

        options_layout.addWidget(QLabel("Frame Delay (ms):"))
        self._delay_spin = QSpinBox()
        # 20ms minimum keeps GIF exports from hitting extreme frame rates.
        self._delay_spin.setRange(20, 10000)
        self._delay_spin.setValue(100)
        self._delay_spin.setSingleStep(10)
        options_layout.addWidget(self._delay_spin)

        options_layout.addWidget(QLabel("Loop Count:"))
        self._loop_spin = QSpinBox()
        self._loop_spin.setRange(0, 999)
        self._loop_spin.setValue(0)
        self._loop_spin.setToolTip("0 = infinite loop")
        options_layout.addWidget(self._loop_spin)
        options_layout.addStretch()
        content.addWidget(options_frame)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output GIF:"))
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Select output .gif file")
        output_row.addWidget(self._output_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        output_row.addWidget(browse_btn)
        content.addLayout(output_row)

        create_btn = QPushButton("🎬 Create GIF")
        create_btn.setObjectName("primary_btn")
        create_btn.clicked.connect(self._create_gif)
        content.addWidget(create_btn)

    def _refresh_ffmpeg_status(self):
        if ffmpeg_available():
            self._ffmpeg_status.setText("✅ FFmpeg available — GIFs will use the bundled encoder.")
        else:
            self._ffmpeg_status.setText(
                "ℹ FFmpeg will be prepared on first export — Pillow is the fallback."
            )

    def _add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Images",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not files:
            return
        existing = set(self._frame_paths())
        for path in files:
            if path in existing:
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._frame_list.addItem(item)
        self._renumber_items()

    def _remove_selected(self):
        for item in self._frame_list.selectedItems():
            row = self._frame_list.row(item)
            self._frame_list.takeItem(row)
        self._renumber_items()

    def _clear_frames(self):
        self._frame_list.clear()

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GIF",
            "output.gif",
            "GIF Images (*.gif);;All Files (*)",
        )
        if path:
            if not path.lower().endswith(".gif"):
                path += ".gif"
            self._output_edit.setText(path)

    def _frame_paths(self) -> list[str]:
        paths = []
        for i in range(self._frame_list.count()):
            item = self._frame_list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                paths.append(path)
        return paths

    def _renumber_items(self, *args):
        for i in range(self._frame_list.count()):
            item = self._frame_list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            label = Path(path).name if path else "Untitled"
            item.setText(f"{i + 1}.  {label}")

    def _create_gif(self):
        frames = self._frame_paths()
        if not frames:
            QMessageBox.warning(self, "No Frames", "Add at least one image to create a GIF.")
            return
        output = self._output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "No Output", "Select an output GIF file.")
            return

        try:
            used_ffmpeg = create_gif(
                frames,
                output,
                duration_ms=self._delay_spin.value(),
                loop=self._loop_spin.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "GIF Failed", str(exc))
            return

        method = "FFmpeg" if used_ffmpeg else "Pillow"
        QMessageBox.information(
            self,
            "GIF Created",
            f"✅ GIF written to:\n{output}\n\nEncoder: {method}",
        )
