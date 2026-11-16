"""Compact colored chips with real solid/dashed visibility outlines."""

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate

from picer.ui import colors_for, ui_icon


class TagDelegate(QStyledItemDelegate):
    def __init__(self, parent, library=False):
        super().__init__(parent)
        self.library = library

    def sizeHint(self, option, index):
        tag = index.data(Qt.ItemDataRole.UserRole)
        width = min(200, option.fontMetrics.horizontalAdvance(tag["name"]) + 42)
        return QSize(width, 40 if self.library else 32)

    def paint(self, painter, option, index):
        tag = index.data(Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        colors = colors_for(self.parent())
        if self.library and option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["hover"]))
            painter.drawRoundedRect(rect, 6, 6)
        if self.library:
            rect.setWidth(
                min(
                    rect.width() - 76,
                    max(48, min(180, option.fontMetrics.horizontalAdvance(tag["name"]) + 22)),
                )
            )
        color = QColor(tag["color"])
        pen = QPen(color, 1)
        if not tag["visible"]:
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setOpacity(0.65)
        painter.setPen(pen)
        tint = QColor(color)
        tint.setAlpha(18)
        painter.setBrush(tint)
        painter.drawRoundedRect(rect, 6, 6)
        text_rect = rect.adjusted(10, 0, -10 if self.library else -25, 0)
        painter.setPen(color)
        text = option.fontMetrics.elidedText(
            tag["name"], Qt.TextElideMode.ElideRight, max(1, int(text_rect.width()))
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.setOpacity(1)
        if self.library:
            eye = QRect(option.rect.right() - 62, option.rect.center().y() - 9, 18, 18)
            ui_icon("eye" if tag["visible"] else "eye-off", colors["muted"]).paint(painter, eye)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(
                option.rect.adjusted(option.rect.width() - 30, 0, 0, 0),
                Qt.AlignmentFlag.AlignCenter,
                "⋮",
            )
        else:
            painter.drawText(
                rect.adjusted(rect.width() - 22, 0, -5, 0), Qt.AlignmentFlag.AlignCenter, "×"
            )
        painter.restore()


class TagList(QListWidget):
    removeRequested = Signal(str)
    visibilityRequested = Signal(str)
    editRequested = Signal(str)

    def __init__(self, *, library=False):
        super().__init__()
        self.library = library
        self.setFrameShape(self.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setStyleSheet("QListWidget { border: none; background: transparent; }")
        self.setItemDelegate(TagDelegate(self, library))
        if not library:
            self.setFlow(self.Flow.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(self.ResizeMode.Adjust)
            self.setSpacing(3)
            self.setMaximumHeight(160)
            self.setMinimumHeight(70)

    def fit_height(self):
        if self.library:
            return
        available = max(1, self.viewport().width())
        rows, used = 1, 0
        for index in range(self.count()):
            width = self.item(index).sizeHint().width() + self.spacing() * 2
            if used and used + width > available:
                rows, used = rows + 1, 0
            used += width
        height = min(160, rows * 38)
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and event.button() == Qt.MouseButton.LeftButton:
            rect = self.visualItemRect(item)
            distance = rect.right() - event.position().x()
            tag_id = item.data(Qt.ItemDataRole.UserRole)["id"]
            if distance < (30 if self.library else 24):
                (self.editRequested if self.library else self.removeRequested).emit(tag_id)
                event.accept()
                return
            if self.library and distance < 70:
                self.visibilityRequested.emit(tag_id)
                event.accept()
                return
        super().mouseReleaseEvent(event)
