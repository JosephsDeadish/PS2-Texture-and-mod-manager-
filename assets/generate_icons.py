#!/usr/bin/env python3
"""
Generate PNG and ICO icon files from assets/icon.svg.

Usage:
    python3 assets/generate_icons.py

Requires PyQt6 (already a project dependency).
Produces:
    assets/icon_256.png   — 256×256 PNG (used by Linux / macOS)
    assets/icon.ico       — multi-resolution ICO (used by Windows)
    assets/icon_48.png    — 48×48 PNG
    assets/icon_32.png    — 32×32 PNG
    assets/icon_16.png    — 16×16 PNG
"""

import os
import sys
import struct
import io

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QPixmap, QPainter, QImage
from PyQt6.QtCore import Qt, QSize


def render_svg_to_pixmap(svg_path: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(svg_path)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def pixmap_to_png_bytes(pixmap: QPixmap) -> bytes:
    buf = io.BytesIO()
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    # Save as PNG via Qt
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    pixmap.save(tmp, "PNG")
    with open(tmp, "rb") as f:
        data = f.read()
    os.unlink(tmp)
    return data


def build_ico(sizes_and_png: list) -> bytes:
    """
    Build a Windows .ico file from a list of (size, png_bytes) tuples.
    ICO format reference: https://en.wikipedia.org/wiki/ICO_(file_format)
    """
    n = len(sizes_and_png)
    header_size = 6          # ICONDIR
    entry_size = 16          # ICONDIRENTRY per image
    data_offset = header_size + n * entry_size

    entries = []
    data_chunks = []
    offset = data_offset

    for size, png_data in sizes_and_png:
        entries.append((size, png_data, offset))
        data_chunks.append(png_data)
        offset += len(png_data)

    out = bytearray()

    # ICONDIR
    out += struct.pack("<HHH", 0, 1, n)  # reserved, type=1 (icon), count

    # ICONDIRENTRY for each image
    for size, png_data, off in entries:
        w = size if size < 256 else 0
        h = size if size < 256 else 0
        out += struct.pack("<BBBBHHII",
            w, h,         # width, height (0 = 256)
            0,            # color count (0 = more than 256)
            0,            # reserved
            1,            # planes
            32,           # bit count
            len(png_data),  # size of image data
            off,          # offset of image data
        )

    # Image data
    for chunk in data_chunks:
        out += chunk

    return bytes(out)


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    svg_path = os.path.join(_here, "icon.svg")
    if not os.path.exists(svg_path):
        print(f"ERROR: {svg_path} not found")
        sys.exit(1)

    sizes = [16, 32, 48, 256]
    png_by_size = {}

    for size in sizes:
        pixmap = render_svg_to_pixmap(svg_path, size)
        png_data = pixmap_to_png_bytes(pixmap)
        png_by_size[size] = png_data

        out_path = os.path.join(_here, f"icon_{size}.png")
        with open(out_path, "wb") as f:
            f.write(png_data)
        print(f"  Wrote {out_path} ({len(png_data):,} bytes)")

    # Build ICO (use 16, 32, 48, 256)
    ico_sizes = [(s, png_by_size[s]) for s in sizes]
    ico_data = build_ico(ico_sizes)
    ico_path = os.path.join(_here, "icon.ico")
    with open(ico_path, "wb") as f:
        f.write(ico_data)
    print(f"  Wrote {ico_path} ({len(ico_data):,} bytes)")

    print("Done.")


if __name__ == "__main__":
    main()
