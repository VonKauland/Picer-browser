"""Transparent, feathered photo carousel with no tray or scrollbars."""

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget


class PreviewStrip(QWidget):
    def __init__(self, owner):
        # An independent host overlay survives dock hiding/reparenting and never
        # receives Qt.Popup's implicit outside-click dismissal or mouse grab.
        super().__init__(owner.dock.parentWidget())
        self.owner = owner
        self.items = []
        self.thumbnail_size = 80
        self.center_index = 0
        self.reveal = 0.0
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAccessibleName("图片缩略预览")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.reposition)
        self.anchor_timer = QTimer(self)
        self.anchor_timer.setInterval(16)
        self.anchor_timer.timeout.connect(self.reposition)
        owner.dock.installEventFilter(self)
        owner.dock.parentWidget().installEventFilter(self)
        self.hide()

    def reposition(self):
        if self.isVisible():
            controller = self.owner.dock.parentWidget().panel_hovers.controllers.get(
                self.owner.context.plugin_id
            )
            if controller is None:
                self.hide()
                return
            width, height = controller.bounds().width(), self.thumbnail_size + 18
            if controller.popup is not None:
                top = controller.popup.geometry().top()
            elif not self.owner.dock.isHidden():
                top = self.owner.dock.geometry().top()
            else:
                top = self.parentWidget().height()
            target = QRect(
                (self.parentWidget().width() - width) // 2,
                top - height - 8 + round(12 * (1 - self.reveal)),
                width,
                height,
            )
            if self.owner.dock.property("previewGeometry") != target:
                self.owner.dock.setProperty("previewGeometry", target)
                controller.collection.layout_strips()
            if target != self.geometry():
                changed_width = target.width() != self.width()
                self.setGeometry(target)
                if changed_width:
                    self.owner.refresh_timer.start()
                self.raise_()
                controller.strip.raise_()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize) and self.isVisible():
            self.layout_timer.start(0)
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close):
            self.layout_timer.start(0)
        return False

    def tile_rect(self, position):
        selected = self.items[position][0] == self.center_index
        size = self.thumbnail_size if selected else round(self.thumbnail_size * 0.88)
        size *= 0.94 + 0.06 * self.reveal
        center = self.width() / 2 + (self.items[position][0] - self.center_index) * (
            self.thumbnail_size + 8
        )
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
                painter.setPen(QColor(self.owner.context.accent_color()))
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        fade = QLinearGradient(1, 0, self.width() - 1, 0)
        for stop, alpha in ((0, 0), (0.08, 255), (0.92, 255), (1, 0)):
            fade.setColorAt(stop, QColor(255, 255, 255, alpha))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(layer.rect(), fade)
        painter.end()
        output = QPainter(self)
        output.setOpacity(self.reveal)
        output.drawPixmap(0, 0, layer)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for position, item in enumerate(self.items):
                if self.tile_rect(position).contains(event.position()):
                    paths = self.owner.context.image_paths()
                    if 0 <= item[0] < len(paths) and str(paths[item[0]]) == item[1]:
                        self.owner.context.jump_to(item[0])
                    return

    def move_center(self, delta):
        paths = self.owner.context.image_paths()
        if paths:
            index = max(0, min(len(paths) - 1, self.center_index + delta))
            self.owner.refresh_preview(center=index)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self.move_center(-1 if delta > 0 else 1)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.owner.context.jump_to(self.center_index)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.move_center(1 if event.key() == Qt.Key.Key_Right else -1)
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        self.anchor_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.owner.dock.setProperty("previewGeometry", None)
        controller = self.owner.dock.parentWidget().panel_hovers.controllers.get(
            self.owner.context.plugin_id
        )
        if controller:
            controller.collection.layout_strips()
        self.anchor_timer.stop()
        self.layout_timer.stop()
        if not self.owner.preview_open:
            self.owner.compact(False, animate=False)
        super().hideEvent(event)
