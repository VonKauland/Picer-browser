"""Compact navigator and curve controls; modifiers never duplicate the photo preview."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from picer.i18n import tr
from picer.ui import colors_for


class Navigator(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setMinimumHeight(90)
        self.setMaximumHeight(110)
        self.setAccessibleName(tr("图像导航器"))
        self.target = QRectF()
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        view = self.session.host.view
        pixmap = view.image_item.pixmap()
        if pixmap.isNull():
            return
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        ratio = min(rect.width() / pixmap.width(), rect.height() / pixmap.height())
        size = QPointF(pixmap.width() * ratio, pixmap.height() * ratio)
        self.target = QRectF(
            rect.center().x() - size.x() / 2, rect.center().y() - size.y() / 2, size.x(), size.y()
        )
        p.drawPixmap(self.target.toRect(), pixmap)
        source = view.image_item.sceneBoundingRect()
        visible = view.mapToScene(view.viewport().rect()).boundingRect().intersected(source)
        if not source.isEmpty():
            viewport = QRectF(
                self.target.x() + (visible.x() - source.x()) / source.width() * size.x(),
                self.target.y() + (visible.y() - source.y()) / source.height() * size.y(),
                visible.width() / source.width() * size.x(),
                visible.height() / source.height() * size.y(),
            )
            p.setPen(QPen(QColor(colors_for(self)["accent"]), 1))
            p.drawRect(viewport.adjusted(0.5, 0.5, -0.5, -0.5))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pan(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.pan(event.position())

    def pan(self, point):
        if self.target.isEmpty():
            return
        rect = self.session.host.view.image_item.sceneBoundingRect()
        x = max(0, min(1, (point.x() - self.target.x()) / self.target.width()))
        y = max(0, min(1, (point.y() - self.target.y()) / self.target.height()))
        self.session.host.view.centerOn(rect.x() + x * rect.width(), rect.y() + y * rect.height())
        self.update()


class CurveEditor(QWidget):
    changed = Signal(object)

    def __init__(self, parent=None, *, editable=True):
        super().__init__(parent)
        self.setMinimumHeight(145 if editable else 70)
        self.setMaximumHeight(200 if editable else 85)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("曲线节点编辑器") if editable else tr("色阶直方图"))
        self.nodes, self.selected, self.histogram = [[0, 0], [255, 255]], None, []
        self.editable = editable

    def area(self):
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.area()
        p.fillRect(rect, QColor("#252527"))
        p.setPen(QPen(QColor("#454549"), 1))
        for n in range(5):
            x, y = rect.left() + rect.width() * n / 4, rect.top() + rect.height() * n / 4
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        if self.histogram and max(self.histogram):
            path = QPainterPath(QPointF(rect.left(), rect.bottom()))
            maximum = max(self.histogram)
            for n, value in enumerate(self.histogram):
                path.lineTo(
                    rect.left() + n / 255 * rect.width(),
                    rect.bottom() - math.sqrt(value / maximum) * rect.height(),
                )
            path.lineTo(rect.bottomRight())
            p.fillPath(path, QColor(180, 180, 185, 90))
        if not self.editable:
            return
        p.setPen(QPen(QColor(colors_for(self)["accent"]), 1.7))
        path = QPainterPath()
        for n, (x, y) in enumerate(self.nodes):
            point = QPointF(
                rect.left() + x / 255 * rect.width(), rect.bottom() - y / 255 * rect.height()
            )
            if n:
                path.lineTo(point)
            else:
                path.moveTo(point)
        p.drawPath(path)
        for n, (x, y) in enumerate(self.nodes):
            p.setBrush(QColor(colors_for(self)["accent"] if n == self.selected else "#EEEEEE"))
            p.drawEllipse(
                QPointF(
                    rect.left() + x / 255 * rect.width(), rect.bottom() - y / 255 * rect.height()
                ),
                3,
                3,
            )

    def position(self, point):
        rect = self.area()
        return [
            round(max(0, min(255, (point.x() - rect.left()) / rect.width() * 255))),
            round(max(0, min(255, (rect.bottom() - point.y()) / rect.height() * 255))),
        ]

    def mousePressEvent(self, event):
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        point = self.position(event.position())
        nearest = min(range(len(self.nodes)), key=lambda i: math.dist(self.nodes[i], point))
        if math.dist(self.nodes[nearest], point) > 14:
            if len(self.nodes) >= 16 or any(node[0] == point[0] for node in self.nodes):
                return
            self.nodes.append(point)
            self.nodes.sort()
            nearest = self.nodes.index(point)
        self.selected = nearest
        self.changed.emit([node[:] for node in self.nodes])
        self.update()

    def mouseMoveEvent(self, event):
        if (
            self.editable
            and self.selected is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.set_selected(*self.position(event.position()))

    def set_selected(self, x, y):
        if self.selected is None:
            return
        n = self.selected
        left = self.nodes[n - 1][0] + 1 if n else 0
        right = self.nodes[n + 1][0] - 1 if n < len(self.nodes) - 1 else 255
        self.nodes[n] = [max(left, min(right, x)), max(0, min(255, y))]
        self.changed.emit([node[:] for node in self.nodes])
        self.update()

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace} and (
            self.selected is not None and 0 < self.selected < len(self.nodes) - 1
        ):
            self.nodes.pop(self.selected)
            self.selected = None
            self.changed.emit([node[:] for node in self.nodes])
            self.update()
            event.accept()
        else:
            super().keyPressEvent(event)
