"""Render the source SVG into desktop PNG and multi-resolution Windows ICO assets."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


def prepare_icons(source: Path, destination: Path) -> None:
    app = QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid icon source: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not render PNG icon")
        images.append((size, bytes(data)))
        if size == 256:
            (destination / "picer.png").write_bytes(bytes(data))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        )
        offset += len(data)
    (destination / "picer.ico").write_bytes(
        header + b"".join(entries) + b"".join(data for _, data in images)
    )
    (destination / "picer.svg").write_bytes(source.read_bytes())
    # Keep a strong application reference until all rendering has completed.
    assert app is not None
