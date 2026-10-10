"""Compact, transparent image/frame progress for the hidden bottom panel."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

RING_SIZE = 24  # 20 px outer diameter, with a small hover/click target around it.


def paint_ring(painter, rect, fraction, color, width):
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#454549"), width))
    painter.drawEllipse(rect)
    fraction = max(0.0, min(1.0, fraction))
    if fraction:
        painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if fraction == 1:
            painter.drawEllipse(rect)
        else:
            painter.drawArc(rect, 90 * 16, -round(fraction * 360 * 16))


def paint_progress(painter, fraction, frame_fraction, accent):
    paint_ring(painter, QRectF(2, 2, 20, 20), fraction, accent, 1.8)
    if frame_fraction is not None:
        paint_ring(painter, QRectF(6, 6, 12, 12), frame_fraction, "#C9CCD2", 1.3)
