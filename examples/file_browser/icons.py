"""Small, neutral frosted-glass folder icons, independent of host skins."""

from PIL import Image, ImageFilter
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def folder_icon(pictures=False, preview=None, *, network=False):
    size = 128
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    back = QPainterPath()
    back.moveTo(14, 106)
    back.lineTo(14, 24)
    back.quadTo(14, 14, 24, 14)
    back.lineTo(42, 14)
    back.quadTo(46, 14, 50, 22)
    back.lineTo(55, 28)
    back.lineTo(104, 28)
    back.quadTo(114, 28, 114, 38)
    back.lineTo(114, 106)
    back.closeSubpath()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(14, 14, 114, 110)
    gradient.setColorAt(0, QColor("#929296"))
    gradient.setColorAt(0.45, QColor("#59595E"))
    gradient.setColorAt(1, QColor("#303034"))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor("#A0A0A4"), 1.5))
    painter.drawPath(back)
    if network:
        # The enlarged globe rises above the rear sleeve, with its lower
        # hemisphere softened by the same glass pass as the existing cards.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#E5E5E8"), 2.8))
        globe = QRectF(38, 6, 78, 78)
        painter.drawEllipse(globe)
        painter.drawEllipse(QRectF(58, 6, 38, 78))
        painter.drawLine(38, 45, 116, 45)
        for y, bend in ((26, 5), (64, -5)):
            latitude = QPainterPath()
            latitude.moveTo(43, y)
            latitude.quadTo(77, y + bend, 111, y)
            painter.drawPath(latitude)
    else:
        paint_card(painter, pictures, preview)
    painter.end()
    return glass_sleeve(image, size)


def paint_card(painter, pictures, preview):
    painter.setPen(Qt.PenStyle.NoPen)
    card = QRectF(52, 34, 54, 68)
    painter.setBrush(QColor("#DDDDDF"))
    painter.drawRoundedRect(card, 7, 7)
    painter.setBrush(QColor("#7B7B80"))
    if preview is not None and not preview.isNull():
        # A smaller, front-facing card sits inside the sleeve on its right.
        clipped = QPainterPath()
        clipped.addRoundedRect(card, 7, 7)
        photo = preview.scaled(
            54,
            68,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.save()
        painter.setClipPath(clipped)
        painter.drawImage(
            card,
            photo,
            QRectF((photo.width() - 54) / 2, (photo.height() - 68) / 2, 54, 68),
        )
        painter.restore()
    elif pictures:
        painter.drawEllipse(QRectF(55, 40, 10, 10))
        mountain = QPainterPath()
        mountain.moveTo(54, 69)
        mountain.lineTo(61, 55)
        mountain.lineTo(69, 62)
        mountain.lineTo(84, 46)
        mountain.lineTo(104, 69)
        mountain.closeSubpath()
        painter.drawPath(mountain)
    else:
        for y in (43, 54, 65, 76):
            painter.drawRoundedRect(QRectF(60, y, 36, 5), 2.5, 2.5)


def glass_sleeve(image, size):
    blurred = Image.frombytes("RGBA", (size, size), bytes(image.bits())).filter(
        ImageFilter.GaussianBlur(3.5)
    )
    haze = QImage(blurred.tobytes(), size, size, QImage.Format.Format_RGBA8888).copy()
    front = QPainterPath()
    front.moveTo(12, 106)
    front.lineTo(12, 64)
    front.quadTo(12, 57, 20, 57)
    front.lineTo(35, 57)
    front.quadTo(40, 57, 46, 63)
    front.quadTo(51, 69, 58, 69)
    front.lineTo(108, 69)
    front.quadTo(116, 69, 116, 77)
    front.lineTo(116, 106)
    front.quadTo(116, 116, 106, 116)
    front.lineTo(22, 116)
    front.quadTo(12, 116, 12, 106)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.save()
    painter.setClipPath(front)
    painter.drawImage(0, 0, haze)
    tint = QLinearGradient(0, 57, 0, 116)
    tint.setColorAt(0, QColor(150, 150, 155, 125))
    tint.setColorAt(0.45, QColor(100, 100, 105, 160))
    tint.setColorAt(1, QColor(58, 58, 62, 205))
    painter.fillPath(front, tint)
    sheen = QLinearGradient(12, 0, 116, 0)
    sheen.setColorAt(0, QColor(255, 255, 255, 35))
    sheen.setColorAt(0.25, QColor(255, 255, 255, 8))
    sheen.setColorAt(0.7, QColor(255, 255, 255, 0))
    sheen.setColorAt(1, QColor(255, 255, 255, 18))
    painter.fillPath(front, sheen)
    painter.restore()
    edge = QLinearGradient(0, 57, 0, 116)
    edge.setColorAt(0, QColor("#CCCCCF"))
    edge.setColorAt(1, QColor("#77777B"))
    painter.setPen(QPen(edge, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(front)
    painter.end()
    normal = QPixmap.fromImage(image)
    active = image.copy()
    painter = QPainter(active)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    painter.fillRect(active.rect(), QColor(255, 255, 255, 14))
    painter.end()
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(QPixmap.fromImage(active) if mode == QIcon.Mode.Active else normal, mode)
    return icon
