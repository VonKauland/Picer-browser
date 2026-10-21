"""Borderless Explorer thumbnails; no preferences, plugins or viewer startup."""

import argparse
import os
import struct
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPolygonF

# Original square pixel lettering: no installed font or redistributed font required.
GLYPHS = dict(
    zip(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (
            "11111/10001/10011/10101/11001/10001/11111",
            "00100/01100/00100/00100/00100/00100/01110",
            "11111/00001/00001/11111/10000/10000/11111",
            "11111/00001/00001/01111/00001/00001/11111",
            "10001/10001/10001/11111/00001/00001/00001",
            "11111/10000/10000/11111/00001/00001/11111",
            "11111/10000/10000/11111/10001/10001/11111",
            "11111/00001/00010/00100/01000/01000/01000",
            "11111/10001/10001/11111/10001/10001/11111",
            "11111/10001/10001/11111/00001/00001/11111",
            "01110/11011/10001/11111/10001/10001/10001",
            "11110/10001/10001/11110/10001/10001/11110",
            "11111/10000/10000/10000/10000/10000/11111",
            "11110/10001/10001/10001/10001/10001/11110",
            "11111/10000/10000/11110/10000/10000/11111",
            "11111/10000/10000/11110/10000/10000/10000",
            "11111/10000/10000/10111/10001/10001/11111",
            "10001/10001/10001/11111/10001/10001/10001",
            "11111/00100/00100/00100/00100/00100/11111",
            "00111/00001/00001/00001/10001/10001/11111",
            "10001/10010/10100/11000/10100/10010/10001",
            "10000/10000/10000/10000/10000/10000/11111",
            "10001/11011/10101/10101/10001/10001/10001",
            "10001/11001/11001/10101/10011/10011/10001",
            "11111/10001/10001/10001/10001/10001/11111",
            "11111/10001/10001/11111/10000/10000/10000",
            "11111/10001/10001/10001/10101/10010/11101",
            "11111/10001/10001/11111/10100/10010/10001",
            "11111/10000/10000/11111/00001/00001/11111",
            "11111/00100/00100/00100/00100/00100/00100",
            "10001/10001/10001/10001/10001/10001/11111",
            "10001/10001/10001/10001/01010/01010/00100",
            "10001/10001/10001/10101/10101/11011/10001",
            "10001/01010/01010/00100/01010/01010/10001",
            "10001/10001/01010/00100/00100/00100/00100",
            "11111/00001/00010/00100/01000/10000/11111",
        ),
        strict=True,
    )
)
MAX_INPUT_BYTES = 512 * 1024 * 1024
PROVIDER_CLSID = "{7759159A-5A69-4BA7-9C87-2144E743C8DD}"
THUMBNAIL_IID = "{E357FCCD-A995-4576-B01F-234630154E96}"


def corner_polygon(width, height, *, bottom=False):
    extent = min(max(min(width, height) * 0.32, 24), min(width, height) * 0.72)
    points = [(0, extent * 0.45), (extent * 0.45, 0), (extent, 0), (0, extent)]
    if bottom:
        points = [(width - x, height - y) for x, y in points]
    return QPolygonF([QPointF(x, y) for x, y in points]), extent


def matte_texture():
    texture = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    state = 0x50494345
    for y in range(64):
        for x in range(64):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            gray = 47 + ((state >> 24) % 15) - 7
            texture.setPixelColor(x, y, QColor(gray, gray, gray))
    return texture


def render_thumbnail(image, suffix, edge):
    """Preserve the complete oriented image; draw only two neutral corner straps."""
    if image.isNull() or not 16 <= edge <= 1024:
        raise ValueError("Invalid thumbnail image or size")
    image = image.scaled(
        edge, edge, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    width, height = image.width(), image.height()
    if min(width, height) < 16:
        return image  # Very thin panoramas cannot fit a legible corner label.
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    texture = QBrush(matte_texture())
    for bottom in (False, True):
        polygon, extent = corner_polygon(width, height, bottom=bottom)
        painter.save()
        painter.setClipRect(image.rect())
        painter.setPen(QColor(103, 103, 103))
        painter.setBrush(texture)
        painter.drawPolygon(polygon)
        if bottom:
            painter.setClipPath(_polygon_path(polygon), Qt.ClipOperation.IntersectClip)
            label = "".join(c for c in suffix.upper().lstrip(".") if c in GLYPHS)[:12] or "IMG"
            units = len(label) * 6 - 1
            scale = min(extent * 0.89 / units, extent * 0.25 / 7)
            painter.translate(width - extent * 0.3625, height - extent * 0.3625)
            painter.rotate(-45)
            painter.scale(scale, scale)
            painter.translate(-units / 2, -3.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(238, 238, 238))
            for index, letter in enumerate(label):
                for y, row in enumerate(GLYPHS[letter].split("/")):
                    for x, cell in enumerate(row):
                        if cell == "1":
                            painter.drawRect(QRectF(index * 6 + x, y, 1, 1))
        painter.restore()
    painter.end()
    return image


def _polygon_path(polygon):
    from PySide6.QtGui import QPainterPath

    path = QPainterPath()
    path.addPolygon(polygon)
    return path


def write_bitmap(image, target):
    """A bounded top-down premultiplied BGRA DIB, consumed by the native provider."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    pixels = bytes(image.constBits())
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    header += struct.pack(
        "<IiiHHIIiiII", 40, image.width(), -image.height(), 1, 32, 0, len(pixels), 0, 0, 0, 0
    )
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(header + pixels)
    temporary.replace(target)


def decode_stream_image(source, edge):
    from PySide6.QtGui import QImageReader

    from picer.imaging import read_image

    suffix = source.suffix.lower()
    if suffix != ".img":
        return read_image(source, edge=edge), suffix
    # COM streams need not expose a filename. Decode content without inventing an
    # original extension, and never rename the stream copy (cleanup owns its name).
    with source.open("rb") as handle:
        signature = handle.read(4)
    if signature == b"8BPS":
        return read_image(source, edge=edge, format_hint=".psd"), "PSD"
    import rawpy

    try:
        return read_image(source, edge=edge, format_hint=".raw"), "RAW"
    except rawpy.LibRawError:
        pass
    detected = bytes(QImageReader.imageFormat(str(source))).decode("ascii")
    return read_image(source, edge=edge), detected or "IMG"


def main(argv=None):
    # Called before importing app/window; never load plugins or touch application data.
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("edge", type=int)
    args = parser.parse_args(argv)
    if not 16 <= args.edge <= 1024:
        return 2
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QGuiApplication

    from picer.imaging import supported_suffixes

    app = QGuiApplication.instance() or QGuiApplication(["Picer Thumbnail"])
    directory = args.directory.resolve()
    sources = list(directory.glob("source.*"))
    if len(sources) != 1 or sources[0].stat().st_size > MAX_INPUT_BYTES:
        return 2
    source = sources[0]
    suffix = source.suffix.lower()
    if suffix not in supported_suffixes() and suffix != ".img":
        return 2
    try:
        image, suffix = decode_stream_image(source, args.edge)
        result = render_thumbnail(image, suffix, args.edge)
        write_bitmap(result, directory / "thumbnail.bmp")
        return 0
    except Exception:
        return 1
    finally:
        # Keep the application alive until all QPainter/QImage resources have detached.
        _ = app
