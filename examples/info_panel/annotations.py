"""Compact, directly clickable half-star ratings and six color classifications."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from picer.annotations import CATEGORIES
from picer.i18n import tr
from picer.ui import colors_for


class Annotations(QWidget):
    ratingChanged = Signal(float)
    categoryChanged = Signal(str)
    ROW_HEIGHT = 33
    START = 34
    STAR_STEP = 15
    COLOR_STEP = 19

    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.category = ""
        self.show_rating = self.show_categories = True
        self.setFixedHeight(self.ROW_HEIGHT * 2)
        self.setMinimumWidth(154)
        self.setMouseTracking(True)
        self.setAccessibleName(tr("半星评分与颜色分类"))
        self.setToolTip(tr("点击星星以半星评分；再次点击清除。点击颜色加入分类，再次点击移除。"))

    def configure(self, rating, categories):
        self.show_rating, self.show_categories = rating, categories
        self.setFixedHeight(self.ROW_HEIGHT * (int(rating) + int(categories)))
        self.setVisible(rating or categories)
        self.update()

    def set_values(self, value, category):
        self.value = (
            max(0.0, min(5.0, round(value * 2) / 2))
            if type(value) in (int, float) and math.isfinite(value)
            else 0.0
        )
        self.category = (
            category if isinstance(category, str) and category in {c[0] for c in CATEGORIES} else ""
        )
        self.update()

    def star_path(self, center):
        path = QPainterPath()
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            radius = 5.5 if index % 2 == 0 else 2.5
            point = center + QPointF(math.cos(angle) * radius, math.sin(angle) * radius)
            path.moveTo(point) if index == 0 else path.lineTo(point)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isEnabled() else 0.4)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        colors = colors_for(self)
        painter.setPen(QColor(colors["border"]))
        painter.drawLine(0, 0, self.width(), 0)
        if self.show_rating:
            y = 19 if self.show_categories else self.ROW_HEIGHT / 2
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRectF(0, y - 10, 30, 20), Qt.AlignmentFlag.AlignVCenter, tr("评分"))
            for index in range(5):
                x = self.START + index * self.STAR_STEP
                path = self.star_path(QPointF(x + self.STAR_STEP / 2, y))
                painter.setPen(QPen(QColor(colors["muted"]), 0.7))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                fraction = max(0.0, min(1.0, self.value - index))
                painter.save()
                painter.setClipRect(QRectF(x, y - 7, self.STAR_STEP * fraction, 14))
                painter.fillPath(path, QColor(colors["accent"]))
                painter.restore()
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(
                QRectF(113, y - 10, 30, 20), Qt.AlignmentFlag.AlignVCenter, f"{self.value:g}"
            )
        if self.show_categories:
            y = 47 if self.show_rating else self.ROW_HEIGHT / 2
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRectF(0, y - 10, 30, 20), Qt.AlignmentFlag.AlignVCenter, tr("分类"))
            for index, (key, _, color) in enumerate(CATEGORIES):
                center = QPointF(self.START + 7.5 + index * self.COLOR_STEP, y)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
                painter.drawEllipse(center, 4, 4)
                if key == self.category:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(colors["text"]), 1))
                    painter.drawEllipse(center, 6, 6)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if self.show_rating and 0 <= y < self.ROW_HEIGHT and self.START <= x < self.START + 75:
            value = (int((x - self.START) / (self.STAR_STEP / 2)) + 1) / 2
            self.value = 0.0 if value == self.value else value
            self.ratingChanged.emit(self.value)
        elif (
            self.show_categories
            and (self.ROW_HEIGHT if self.show_rating else 0) <= y < self.height()
        ):
            for index, (key, _, _) in enumerate(CATEGORIES):
                if abs(x - (self.START + 7.5 + index * self.COLOR_STEP)) <= 8:
                    self.category = "" if key == self.category else key
                    self.categoryChanged.emit(self.category)
                    break
        self.update()
