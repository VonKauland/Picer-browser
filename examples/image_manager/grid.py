"""Virtualized tiles: pixels come exclusively from the host thumbnail service."""

from PySide6.QtCore import QAbstractListModel, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QListView, QStyledItemDelegate

from picer.annotations import CATEGORIES
from picer.ui import colors_for

PALETTE = {key: color for key, _, color in CATEGORIES}


class PhotoModel(QAbstractListModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.paths, self.positions = [], {}

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.paths[index.row()].name
        return None

    def replace(self, paths):
        self.beginResetModel()
        self.paths = paths
        self.positions = {str(path): row for row, path in enumerate(paths)}
        self.endResetModel()


class PhotoGrid(QListView):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSpacing(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QListView { border: none; background: transparent; }")
        self.verticalScrollBar().valueChanged.connect(lambda _: owner.queue_load())
        self.setItemDelegate(PhotoDelegate(owner, self))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def arrange(self):
        columns = max(1, min(4, round(200 / self.owner.size.value())))
        # QListView reserves the potential vertical scrollbar while wrapping,
        # even before it becomes visible. Leave that gutter in the cell budget.
        available = self.viewport().width() - self.verticalScrollBar().sizeHint().width()
        width = max(48, (available - 2) // columns)
        size = QSize(width, round(width * 0.68) + 25)
        if self.gridSize() != size:
            self.setGridSize(size)
            self.doItemsLayout()
        self.owner.queue_load()


class PhotoDelegate(QStyledItemDelegate):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner

    def sizeHint(self, option, index):
        return self.owner.grid.gridSize()

    def paint(self, painter, option, index):
        owner = self.owner
        path = owner.model.paths[index.row()]
        key = str(path)
        colors = colors_for(owner.panel)
        rect = QRectF(option.rect).adjusted(3, 3, -3, -3)
        photo = rect.adjusted(2, 2, -2, -21)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = path == owner.current
        painter.setPen(QPen(QColor(colors["accent"]), 1) if selected else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["hover"]) if selected else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        clip = QPainterPath()
        clip.addRoundedRect(photo, 4, 4)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(photo, QColor("#38383B"))
        image = owner.pixels.get(key)
        if image is not None and not image.isNull():
            source = QRectF(image.rect())
            ratio = photo.width() / max(1, photo.height())
            if source.width() / source.height() > ratio:
                width = source.height() * ratio
                source.setLeft((image.width() - width) / 2)
                source.setWidth(width)
            else:
                height = source.width() / ratio
                source.setTop((image.height() - height) / 2)
                source.setHeight(height)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(photo, image, source)
        mark = owner.notes.get(key, {})
        color = mark.get("color")
        if color in PALETTE:
            center = QPointF(photo.right() - 6, photo.top() + 6)
            glow = QRadialGradient(center, 7)
            tint = QColor(PALETTE[color])
            tint.setAlpha(100)
            glow.setColorAt(0, tint)
            tint.setAlpha(0)
            glow.setColorAt(1, tint)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, 7, 7)
            painter.setBrush(QColor(PALETTE[color]))
            painter.drawEllipse(center, 2.5, 2.5)
        rating = mark.get("rating") or 0
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        if rating:
            text = f"★ {rating:g}"
            width = painter.fontMetrics().horizontalAdvance(text) + 7
            badge = QRectF(photo.right() - width - 2, photo.bottom() - 17, width, 15)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 100))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
        painter.setPen(QColor(colors["text"]))
        text = painter.fontMetrics().elidedText(
            path.name, Qt.TextElideMode.ElideRight, max(1, int(rect.width() - 4))
        )
        painter.drawText(
            rect.adjusted(2, rect.height() - 19, -2, 0), Qt.AlignmentFlag.AlignVCenter, text
        )
        painter.restore()
