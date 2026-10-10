"""Transparent, feathered photo carousel with no tray or scrollbars."""

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget


class PreviewStrip(QWidget):
    def __init__(self, owner):
        super().__init__(
            owner.panel,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.owner = owner
        self.items = []
        self.thumbnail_size = 80
        self.center_index = 0
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAccessibleName("图片缩略预览")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.reposition)
        owner.dock.installEventFilter(self)
        owner.dock.parentWidget().installEventFilter(self)

    def reposition(self):
        if self.isVisible():
            controller = self.owner.dock.parentWidget().panel_hovers.controllers.get(
                self.owner.context.plugin_id
            )
            if controller is None:
                self.hide()
                return
            surface = controller.surface or self.owner.dock.widget()
            origin = surface.mapToGlobal(QPoint())
            self.resize(controller.bounds().width(), self.thumbnail_size + 18)
            self.move(origin.x(), origin.y() - self.height() - 8)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize) and self.isVisible():
            self.layout_timer.start(0)
        if obj is self.owner.dock and event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.hide()
        return False

    def tile_rect(self, position):
        selected = self.items[position][0] == self.center_index
        index = next((i for i, item in enumerate(self.items) if item[0] == self.center_index), 0)
        size = self.thumbnail_size if selected else round(self.thumbnail_size * 0.88)
        center = self.width() / 2 + (position - index) * (self.thumbnail_size + 8)
        return QRectF(center - size / 2, (self.height() - size) / 2, size, size)

    def paintEvent(self, event):
        layer = QPixmap(self.size() * self.devicePixelRatioF())
        layer.setDevicePixelRatio(self.devicePixelRatioF())
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for position, (image_index, _, image) in enumerate(self.items):
            rect = self.tile_rect(position)
            if not rect.intersects(QRectF(self.rect())):
                continue
            # Individual soft shadows, rather than a background behind the strip.
            painter.setPen(Qt.PenStyle.NoPen)
            for spread in range(7, 0, -1):
                painter.setBrush(QColor(0, 0, 0, 5 + (8 - spread)))
                painter.drawRoundedRect(
                    rect.adjusted(-spread, -spread + 3, spread, spread + 3), 6 + spread, 6 + spread
                )
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.save()
            painter.setClipPath(path)
            if not image.isNull():
                side = min(image.width(), image.height())
                source = QRectF((image.width() - side) / 2, (image.height() - side) / 2, side, side)
                painter.drawImage(rect, image, source)
            else:
                painter.fillPath(path, QColor("#303032"))
            painter.restore()
            if image_index == self.center_index:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QColor("#E8FF59"))
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        fade = QLinearGradient(1, 0, self.width() - 1, 0)
        for stop, alpha in ((0, 0), (0.08, 255), (0.92, 255), (1, 0)):
            fade.setColorAt(stop, QColor(255, 255, 255, alpha))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(layer.rect(), fade)
        painter.end()
        output = QPainter(self)
        output.drawPixmap(0, 0, layer)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for position, item in enumerate(self.items):
                if self.tile_rect(position).contains(event.position()):
                    self.owner.context.jump_to(item[0])
                    self.hide()
                    return

    def wheelEvent(self, event):
        if self.items:
            current = next(
                (i for i, item in enumerate(self.items) if item[0] == self.center_index), 0
            )
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                current = max(0, min(len(self.items) - 1, current - (1 if delta > 0 else -1)))
                self.center_index = self.items[current][0]
                self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.owner.context.jump_to(self.center_index)
            self.hide()
        elif self.items and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            current = next(i for i, item in enumerate(self.items) if item[0] == self.center_index)
            current = max(
                0,
                min(len(self.items) - 1, current + (1 if event.key() == Qt.Key.Key_Right else -1)),
            )
            self.center_index = self.items[current][0]
            self.update()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        self.owner.compact(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.owner.compact(False)
        super().hideEvent(event)
