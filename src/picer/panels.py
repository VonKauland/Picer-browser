"""Frosted dock surfaces and hover-only morphing reveals for hidden panels."""

import weakref

from PIL import Image as PillowImage
from PIL import ImageFilter
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import PLUGIN_STYLE


class GlassBackdrop(QObject):
    """One debounced, blurred canvas snapshot shared by every visible glass surface."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.image = QImage()
        self.surfaces = weakref.WeakSet()
        self.capturing = False
        self.captured_signature = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.capture)
        host.view.viewport().installEventFilter(self)
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Wheel)
            and not self.capturing
        ):
            self.invalidate()
        return False

    def signature(self):
        view = self.host.view
        return (
            getattr(self.host, "image_revision", 0),
            view.transform().m11(),
            view.horizontalScrollBar().value(),
            view.verticalScrollBar().value(),
            self.host.size(),
            view.size(),
            self.host.skin_colors["background"],
        )

    def invalidate(self):
        if not self.surfaces or self.signature() == self.captured_signature:
            return
        if not self.timer.isActive():
            self.timer.start()

    def capture(self):
        if not self.host.isVisible():
            return
        self.capturing = True
        try:
            canvas = QImage(self.host.size(), QImage.Format.Format_RGBA8888)
            canvas.fill(QColor("#121722"))
            painter = QPainter(canvas)
            photo = self.host.view.image_item.pixmap()
            if not photo.isNull():
                wallpaper = photo.scaled(
                    canvas.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.setOpacity(0.75)
                painter.drawPixmap(
                    (canvas.width() - wallpaper.width()) // 2,
                    (canvas.height() - wallpaper.height()) // 2,
                    wallpaper,
                )
                painter.setOpacity(1.0)
            viewport = self.host.view.viewport()
            painter.drawPixmap(viewport.mapTo(self.host, QPoint()), viewport.grab())
            painter.end()
            small = canvas.scaled(
                max(1, canvas.width() // 3),
                max(1, canvas.height() // 3),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pixels = PillowImage.frombytes(
                "RGBA", (small.width(), small.height()), bytes(small.bits())
            )
            blurred = pixels.filter(ImageFilter.GaussianBlur(7))
            self.image = (
                QImage(
                    blurred.tobytes(), blurred.width, blurred.height, QImage.Format.Format_RGBA8888
                )
                .copy()
                .scaled(
                    canvas.size(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.captured_signature = self.signature()
            for surface in tuple(self.surfaces):
                try:
                    surface.update()
                except RuntimeError:
                    pass
        finally:
            self.capturing = False


class GlassSurface(QWidget):
    def __init__(self, backdrop, parent=None, *, radius=12, popup=False):
        super().__init__(parent, Qt.WindowType.Popup if popup else Qt.WindowType.Widget)
        self.backdrop, self.radius = backdrop, radius
        self.render_backdrop = True
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        backdrop.surfaces.add(self)

    def paintEvent(self, event):
        if not self.render_backdrop:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.radius, self.radius)
        painter.setClipPath(path)
        if not self.backdrop.image.isNull():
            origin = self.mapTo(self.backdrop.host, QPoint())
            painter.drawImage(self.rect(), self.backdrop.image, QRect(origin, self.size()))
        painter.fillPath(path, QColor(25, 33, 47, 150))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(220, 235, 255, 40), 1))
        painter.drawPath(path)


def dock_surface(host, content):
    content.setProperty("pluginSurface", True)
    original_style = content.styleSheet()
    content.setProperty("picerPanelContent", True)
    content.setStyleSheet(
        PLUGIN_STYLE
        + "\n"
        + original_style
        + '\nQWidget[picerPanelContent="true"] { background: transparent; }'
    )
    surface = GlassSurface(host.glass)
    layout = QVBoxLayout(surface)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(content)
    return surface


def dock_title(host, dock):
    title = GlassSurface(host.glass, radius=8)
    title.setStyleSheet(PLUGIN_STYLE)
    layout = QHBoxLayout(title)
    layout.setContentsMargins(12, 4, 6, 4)
    label = QLabel(dock.windowTitle())
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(label, 1)
    close = QPushButton("×")
    close.setFixedSize(22, 22)
    close.setToolTip("隐藏面板")
    close.clicked.connect(dock.close)
    layout.addWidget(close)
    return title


class RevealEffect(QGraphicsBlurEffect):
    def __init__(self, parent):
        super().__init__(parent)
        self.opacity = 1.0
        self.setBlurHints(QGraphicsBlurEffect.BlurHint.AnimationHint)

    def draw(self, painter):
        painter.save()
        painter.setOpacity(self.opacity)
        super().draw(painter)
        painter.restore()


class HiddenStrip(QWidget):
    def __init__(self, controller):
        super().__init__(controller.host)
        self.controller = controller
        self.setProperty("pluginSurface", True)
        self.setToolTip(controller.dock.windowTitle())
        self.setAccessibleName(controller.dock.windowTitle() + " · 悬停展开")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def enterEvent(self, event):
        self.controller.reveal()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.controller.schedule_collapse()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(161, 182, 210, 165 if self.underMouse() else 90))
        painter.drawRoundedRect(self.rect(), 3, 3)


class MorphPopup(GlassSurface):
    def __init__(self, controller, surface):
        super().__init__(controller.host.glass, controller.host, radius=18)
        self.controller = controller
        self.setStyleSheet(PLUGIN_STYLE)
        self.content = QWidget(self)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(6, 4, 6, 6)
        row = QHBoxLayout()
        row.addWidget(QLabel(controller.dock.windowTitle()), 1)
        close = QPushButton("×")
        close.setFixedSize(24, 24)
        close.clicked.connect(controller.collapse)
        row.addWidget(close)
        layout.addLayout(row)
        layout.addWidget(surface, 1)
        self.effect = RevealEffect(self.content)
        self.content.setGraphicsEffect(self.effect)

    def enterEvent(self, event):
        self.controller.leave_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.controller.schedule_collapse()
        super().leaveEvent(event)


class HiddenPanel(QObject):
    OPEN_MS = 420
    CLOSE_MS = 300

    def __init__(self, collection, dock, plugin_id, manager):
        super().__init__(dock)
        self.collection, self.host, self.dock = collection, collection.host, dock
        self.plugin_id, self.manager = plugin_id, manager
        self.strip = HiddenStrip(self)
        self.popup = None
        self.surface = None
        self.progress = 0.0
        self.expanding = False
        self.last_size = dock.size()
        self.area = self.host.dockWidgetArea(dock)
        self.animation = QVariantAnimation(self)
        self.animation.valueChanged.connect(self.animate)
        self.animation.finished.connect(self.finished)
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(220)
        self.leave_timer.timeout.connect(self.check_leave)
        dock.installEventFilter(self)
        dock.visibilityChanged.connect(self.visibility)
        dock.dockLocationChanged.connect(self.location)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize and not self.dock.isHidden():
            self.last_size = self.dock.size()
        return False

    def location(self, area):
        if area != Qt.DockWidgetArea.NoDockWidgetArea:
            self.area = area
            self.collection.layout_strips()

    def visibility(self, visible):
        if visible:
            self.last_size = self.dock.size()
            self.collapse(immediate=True)
        self.collection.layout_strips()

    def bounds(self):
        viewport = self.host.view.viewport()
        position = viewport.mapTo(self.host, QPoint())
        canvas = QRect(position, viewport.size())
        host = self.host.rect().adjusted(
            12, max(self.host.title_bar.height() + 10, canvas.top()), -12, -12
        )
        host.setBottom(min(host.bottom(), canvas.bottom() - 6))
        width = min(max(self.last_size.width(), 240), host.width())
        height = min(max(self.last_size.height(), 160), host.height())
        if self.area == Qt.DockWidgetArea.BottomDockWidgetArea:
            return QRect(
                max(host.left(), canvas.left() + 6),
                host.bottom() - height + 1,
                min(host.width(), canvas.width() - 12),
                height,
            )
        x = (
            host.left()
            if self.area == Qt.DockWidgetArea.LeftDockWidgetArea
            else host.right() - width + 1
        )
        return QRect(x, host.top(), width, host.height())

    def reveal(self):
        record = self.manager.records.get(self.plugin_id)
        if not self.dock.isHidden() or record is None or record.state != "enabled":
            return
        self.leave_timer.stop()
        if self.popup is None:
            self.surface = self.dock.widget()
            self.surface.render_backdrop = False
            self.surface.setParent(None)
            self.dock.setWidget(None)
            self.popup = MorphPopup(self, self.surface)
            self.target = self.bounds()
            self.popup.content.setFixedSize(self.target.size())
            self.popup.setGeometry(self.strip.geometry())
            self.surface.show()
            self.popup.show()
            self.popup.raise_()
        self.start_animation(True)

    def start_animation(self, expanding):
        self.animation.stop()
        self.expanding = expanding
        self.animation.setStartValue(self.progress)
        self.animation.setEndValue(1.0 if expanding else 0.0)
        self.animation.setDuration(self.OPEN_MS if expanding else self.CLOSE_MS)
        easing = QEasingCurve(
            QEasingCurve.Type.OutBack if expanding else QEasingCurve.Type.InOutCubic
        )
        if expanding:
            easing.setOvershoot(0.55)
        self.animation.setEasingCurve(easing)
        self.animation.start()

    def animate(self, value):
        if self.popup is None:
            return
        self.progress = float(value)
        start = self.strip.geometry()
        end = self.target
        values = [
            round(a + (b - a) * value) for a, b in zip(start.getRect(), end.getRect(), strict=True)
        ]
        values[2], values[3] = max(1, values[2]), max(1, values[3])
        self.popup.setGeometry(QRect(*values))
        self.popup.content.move(
            (self.popup.width() - end.width()) // 2, (self.popup.height() - end.height()) // 2
        )
        fade = max(0.0, min(1.0, (value - 0.2) / 0.8))
        self.popup.effect.opacity = fade
        self.popup.effect.setBlurRadius(12 * (1 - fade))
        self.popup.effect.update()
        shape = QPainterPath()
        radius = 3 + 15 * max(0.0, min(1.0, value))
        shape.addRoundedRect(self.popup.rect(), radius, radius)
        self.popup.setMask(QRegion(shape.toFillPolygon().toPolygon()))
        self.popup.update()

    def schedule_collapse(self):
        if self.popup and self.expanding:
            self.leave_timer.start()

    def check_leave(self):
        if self.popup is None:
            return
        cursor = self.host.mapFromGlobal(QCursor.pos())
        popup_active = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if (
            self.popup.geometry().contains(cursor)
            or self.strip.geometry().contains(cursor)
            or popup_active
        ):
            self.leave_timer.start()
        else:
            self.collapse()

    def collapse(self, checked=False, *, immediate=False):
        if self.popup is None:
            return
        self.leave_timer.stop()
        if immediate:
            self.animation.stop()
            self.progress = 0.0
            self.restore()
        else:
            self.start_animation(False)

    def finished(self):
        if not self.expanding:
            self.restore()

    def restore(self):
        if self.popup is None:
            return
        self.surface.setGraphicsEffect(None)
        self.surface.render_backdrop = True
        self.surface.setParent(self.dock)
        self.dock.setWidget(self.surface)
        self.surface.show()
        self.popup.hide()
        self.popup.deleteLater()
        self.popup, self.surface = None, None
        self.progress = 0.0

    def dispose(self):
        self.collapse(immediate=True)
        self.animation.stop()
        self.leave_timer.stop()
        self.strip.hide()
        self.strip.deleteLater()


class PanelHovers(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.controllers = {}
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.close_all()
            self.layout_strips()
        return False

    def register(self, dock, plugin_id, manager):
        self.controllers[plugin_id] = HiddenPanel(self, dock, plugin_id, manager)

    def unregister(self, plugin_id):
        controller = self.controllers.pop(plugin_id, None)
        if controller:
            controller.dispose()

    def close_all(self):
        for controller in self.controllers.values():
            controller.collapse(immediate=True)

    def layout_strips(self):
        areas = {}
        for controller in self.controllers.values():
            record = controller.manager.records.get(controller.plugin_id)
            hidden = controller.dock.isHidden() and record is not None and record.state == "enabled"
            controller.strip.setVisible(hidden and self.host.isVisible())
            if hidden:
                areas.setdefault(controller.area, []).append(controller)
        for area, controllers in areas.items():
            for index, controller in enumerate(controllers):
                offset = (index - (len(controllers) - 1) / 2) * 96
                if area == Qt.DockWidgetArea.BottomDockWidgetArea:
                    rect = QRect(
                        round(self.host.width() / 2 - 42 + offset), self.host.height() - 9, 84, 5
                    )
                else:
                    x = 4 if area == Qt.DockWidgetArea.LeftDockWidgetArea else self.host.width() - 9
                    rect = QRect(x, round(self.host.height() / 2 - 42 + offset), 5, 84)
                controller.strip.setGeometry(rect)
                controller.strip.raise_()
