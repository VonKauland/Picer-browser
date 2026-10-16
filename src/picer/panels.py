"""Frosted dock surfaces and hover-only morphing reveals for hidden panels."""

import weakref

from PIL import Image as PillowImage
from PIL import ImageFilter
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDockWidget,
    QGraphicsBlurEffect,
    QMenu,
    QTabBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import PLUGIN_STYLE
from picer.progress_ring import RING_SIZE, paint_progress
from picer.theme import COLORS, accent_style
from picer.ui import colors_for

DOCK_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}
PANEL_BOTTOM_GAP = 8


def saved_layout(manager, plugin_id):
    layouts = manager.preferences["ui"].get("panel_layouts", {})
    value = layouts.get(plugin_id, {}) if isinstance(layouts, dict) else {}
    return value if isinstance(value, dict) else {}


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

    def active(self):
        for surface in tuple(self.surfaces):
            try:
                if surface.isVisible() and surface.render_backdrop and surface.uses_glass():
                    return True
            except RuntimeError:
                pass
        return False

    def invalidate(self):
        if not self.active() or self.signature() == self.captured_signature:
            return
        if not self.timer.isActive():
            self.timer.start()

    def capture(self):
        if not self.host.isVisible() or not self.active():
            return
        self.capturing = True
        try:
            canvas = QImage(self.host.size(), QImage.Format.Format_RGBA8888)
            canvas.fill(QColor("#242426"))
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
            # Neutral luminance preserves actual frosted detail without coloring the UI.
            blurred = pixels.convert("L").convert("RGBA").filter(ImageFilter.GaussianBlur(7))
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
        self.frosted = True
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        backdrop.surfaces.add(self)

    def uses_glass(self):
        if not self.frosted or not self.backdrop.host.app_preferences.get("glass", True):
            return False
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, DockSurface):
                return not parent.render_backdrop
            parent = parent.parentWidget()
        return True

    def showEvent(self, event):
        self.backdrop.invalidate()
        super().showEvent(event)

    def paintEvent(self, event):
        if not self.render_backdrop:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        painter.setClipPath(path)
        enabled = self.uses_glass()
        if enabled and not self.backdrop.image.isNull():
            origin = self.mapTo(self.backdrop.host, QPoint())
            painter.drawImage(self.rect(), self.backdrop.image, QRect(origin, self.size()))
        strength = getattr(self.backdrop.host, "app_preferences", {}).get("glass_strength", 70)
        painter.fillPath(path, QColor(48, 48, 50, round(255 - strength * 0.5) if enabled else 255))


class PanelGrip(QWidget):
    """One internal three-dot handle; resize normally, Shift-drag to move a dock."""

    def __init__(self, surface):
        super().__init__(surface)
        self.surface = surface
        self.controller = None
        self.origin = None
        self.moving = False
        self.setToolTip("拖动调整大小 · Shift 拖动换边 · 右键隐藏或停靠")
        self.setAccessibleName("面板三点拖拽条")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors_for(self)["accent"] if self.underMouse() else "#A2A2A6"))
        center = QPointF(self.rect().center())
        for offset in (-6, 0, 6):
            delta = QPointF(offset, 0) if self.surface.horizontal else QPointF(0, offset)
            painter.drawEllipse(center + delta, 1.5, 1.5)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.controller:
            self.origin = event.globalPosition().toPoint()
            self.start_extent = self.controller.current_extent()
            self.moving = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            # Moving a hidden panel is done on its stable edge strip, not a morphing child.
            self.moving = self.moving and not self.controller.dock.isHidden()
            if self.moving:
                self.controller.begin_move()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.origin is None:
            return
        position = event.globalPosition().toPoint()
        if self.moving:
            self.controller.update_move(position)
        else:
            delta = position - self.origin
            amount = -delta.y() if self.surface.horizontal else delta.x()
            if self.controller.area == DOCK_AREAS["right"]:
                amount = -amount
            self.controller.resize_extent(self.start_extent + amount)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.origin is not None:
            self.origin = None
            if self.moving:
                self.controller.end_move(event.globalPosition().toPoint())
            else:
                self.controller.remember_layout()
            self.moving = False
            event.accept()

    def contextMenuEvent(self, event):
        if self.controller:
            self.controller.show_menu(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.controller:
            if self.controller.dock.isHidden():
                self.controller.pin()
            else:
                self.controller.dock.close()


class PanelTab(QAbstractButton):
    """Paint-only scaling leaves the narrow rail and content geometry stable."""

    def __init__(self, surface, target):
        super().__init__(surface.rail)
        self.surface = surface
        self.target = target
        self.scale = 0.0
        self.press_origin = None
        self.dragging = False
        self.setText(target.dock.windowTitle())
        self.setToolTip(self.text() + " · 拖动排序或更换停靠侧")
        self.setAccessibleName(self.text())
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.animate)
        self.clicked.connect(lambda: target.collection.activate_tab(target))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_origin = event.globalPosition().toPoint()
            self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_origin is not None:
            point = event.globalPosition().toPoint()
            if (point - self.press_origin).manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
                self.setDown(False)
                self.target.collection.show_drop_hint(self.target.collection.tab_drop_area(point))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        dragged = self.dragging and event.button() == Qt.MouseButton.LeftButton
        self.press_origin = None
        self.dragging = False
        self.target.collection.show_drop_hint(None)
        if dragged:
            self.setDown(False)
            self.target.collection.drop_tab(self.target, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def animate(self, value):
        self.scale = float(value)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.animation.stop()
        self.scale = 0.0
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QRectF(self.rect()).center()
        painter.translate(center)
        painter.scale(self.scale, self.scale)
        painter.translate(-center)
        selected = self.isChecked()
        ratio = self.devicePixelRatioF()
        background = QImage(self.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
        background.setDevicePixelRatio(ratio)
        background.fill(Qt.GlobalColor.transparent)
        layer = QPainter(background)
        layer.setRenderHint(QPainter.RenderHint.Antialiasing)
        layer.setBrush(
            QColor("#858585" if selected else "#303033" if self.underMouse() else "#252628")
        )
        layer.setPen(QPen(QColor(colors_for(self)["accent"]), 1) if selected else Qt.PenStyle.NoPen)
        layer.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        inward_left = self.surface.area == DOCK_AREAS["left"]
        fade = QLinearGradient(0, 0, self.width(), 0)
        fade.setColorAt(0, QColor(0, 0, 0, 0 if inward_left else 255))
        fade.setColorAt(0.45 if inward_left else 0.55, QColor(0, 0, 0, 255))
        fade.setColorAt(1, QColor(0, 0, 0, 255 if inward_left else 0))
        layer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        layer.fillRect(self.rect(), fade)
        layer.end()
        painter.drawImage(0, 0, background)
        painter.setPen(QColor("#FFFFFF" if selected else "#ADADB2"))
        font = painter.font()
        font.setPixelSize(13)
        painter.setFont(font)
        # Each glyph owns a padded cell: no multiline layout can cross the outline.
        for index, character in enumerate(self.text()):
            cell = QRect(8, 10 + index * 18, self.width() - 16, 18)
            painter.save()
            painter.setClipRect(cell)
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, character)
            painter.restore()


class PanelRail(QWidget):
    """Masked host overlay: only tabs/grip intercept the canvas, never the gaps."""

    def __init__(self, host):
        super().__init__(host)
        self.setStyleSheet("background: transparent; border: none;")
        self.hide()


class DockSurface(GlassSurface):
    def __init__(self, host, content):
        super().__init__(host.glass)
        self.frosted = False
        self.horizontal = False
        self.area = DOCK_AREAS["left"]
        layout = QVBoxLayout(self)
        layout.addWidget(content)
        self.grip = PanelGrip(self)
        self.rail = PanelRail(host)
        self.destroyed.connect(self.rail.deleteLater)
        self.tabs = {}

    def arrange(self, area=None):
        if area is not None:
            self.area = area
        self.horizontal = self.area == DOCK_AREAS["bottom"]
        stacked = bool(self.tabs) and not self.horizontal
        parent = self.rail if stacked else self
        if self.grip.parentWidget() is not parent:
            self.grip.setParent(parent)
            self.grip.show()
        if self.horizontal:
            height = 12
            self.layout().setContentsMargins(0, height, 0, 0)
            self.grip.setGeometry((self.width() - 44) // 2, 0, 44, height)
            self.grip.setCursor(Qt.CursorShape.PointingHandCursor)
            self.grip.setToolTip("右键固定 / 自动隐藏 · 双击切换")
        else:
            left = self.area == DOCK_AREAS["left"]
            self.layout().setContentsMargins(0 if left else 16, 0, 16 if left else 0, 0)
            self.grip.setGeometry(
                self.width() - 16 if left else 0, (self.height() - 44) // 2, 16, 44
            )
            self.grip.setCursor(Qt.CursorShape.SizeHorCursor)
        top = 3
        mask = QRegion()
        for tab in self.tabs.values():
            height = len(tab.text()) * 18 + 20
            tab.setGeometry(0, top, 36, height)
            mask |= QRegion(tab.geometry())
            top += height + 6
            tab.raise_()
        if stacked:
            self.grip.setGeometry(
                10, min(max((self.height() - 44) // 2, top + 8), self.height() - 44), 16, 44
            )
            mask |= QRegion(self.grip.geometry())
            host = self.backdrop.host
            attached = self.window() is host
            if attached:
                left = self.area == DOCK_AREAS["left"]
                origin = self.mapTo(host, QPoint(self.width() - 16 if left else -20, 0))
                self.rail.setGeometry(origin.x(), origin.y(), 36, self.height())
                self.rail.setMask(mask)
            self.rail.setVisible(attached and self.isVisible())
            self.rail.raise_()
        else:
            self.rail.hide()
        self.grip.raise_()
        self.grip.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.arrange()

    def hideEvent(self, event):
        self.rail.hide()
        super().hideEvent(event)

    def set_tabs(self, controllers, selected):
        targets = {item.plugin_id: item for item in controllers}
        for key in list(self.tabs):
            if key not in targets:
                tab = self.tabs.pop(key)
                tab.hide()
                tab.deleteLater()
        for key, target in targets.items():
            if key not in self.tabs:
                self.tabs[key] = PanelTab(self, target)
                self.tabs[key].show()
            self.tabs[key].setChecked(target is selected)
        self.tabs = {key: self.tabs[key] for key in targets}
        self.arrange()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()


def dock_surface(host, content):
    content.setProperty("pluginSurface", True)
    original_style = content.styleSheet()
    content.setProperty("picerPanelOriginalStyle", original_style)
    content.setProperty("picerPanelContent", True)
    content.setStyleSheet(
        accent_style(PLUGIN_STYLE, COLORS["accent"], host.app_preferences["accent_color"])
        + "\n"
        + original_style
        + '\nQWidget[picerPanelContent="true"] { background: transparent; }'
    )
    return DockSurface(host, content)


class DockTitleSpacer(QWidget):
    """Suppress native dock chrome without Qt's invalid (-1, -1) size hints."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(0)

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)


class ProgressDock(QDockWidget):
    """A host-owned bottom overlay, so side docks retain the full window height."""

    def __init__(self, title, host):
        super().__init__(title, host)
        self.setWindowFlags(Qt.WindowType.Widget | Qt.WindowType.FramelessWindowHint)
        self.setProperty("progressPanel", True)
        self.setProperty("compactHeight", 76)


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
    def __init__(self, controller, *, ring=None):
        super().__init__(controller.host)
        self.controller = controller
        self.ring = controller.dock.property("progressPanel") if ring is None else ring
        self.origin = None
        self.dragging = False
        self.setProperty("pluginSurface", True)
        tip = controller.dock.windowTitle() + " · 悬停展开，点击固定"
        if not controller.dock.property("progressPanel"):
            tip += "，拖动左右换边"
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def enterEvent(self, event):
        if self.origin is None:
            self.controller.reveal()
            if self.controller.dock.property("progressPanel"):
                QToolTip.showText(
                    QCursor.pos() + QPoint(12, -30), self.toolTip(), self.controller.host
                )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.controller.schedule_collapse()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.globalPosition().toPoint()
            self.dragging = False
            self.controller.leave_timer.stop()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.origin is None:
            return
        position = event.globalPosition().toPoint()
        if (
            not self.dragging
            and (position - self.origin).manhattanLength() >= QApplication.startDragDistance()
        ):
            self.dragging = True
            self.controller.begin_move()
        if self.dragging:
            self.controller.update_move(position)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.origin is not None:
            self.origin = None
            if self.dragging:
                self.controller.end_move(event.globalPosition().toPoint())
            else:
                self.controller.pin()
            self.dragging = False
            event.accept()

    def contextMenuEvent(self, event):
        self.controller.show_menu(event.globalPos())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.ring:
            host = self.controller.host
            index = host.path_positions.get(host.current_path, -1)
            fraction = (index + 1) / len(host.paths) if host.paths and index >= 0 else 0
            state = host.animation.state
            inner = (state.frame + 1) / state.count if state.active and state.count else None
            paint_progress(painter, fraction, inner, colors_for(self)["accent"])
            return
        color = QColor(colors_for(self)["accent"] if self.underMouse() else "#A2A2A6")
        color.setAlpha(200 if self.underMouse() else 115)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect(), 3, 3)


class MorphPopup(GlassSurface):
    def __init__(self, controller, surface):
        super().__init__(controller.host.glass, controller.host, radius=18)
        self.controller = controller
        self.setStyleSheet(
            accent_style(
                PLUGIN_STYLE, COLORS["accent"], controller.host.app_preferences["accent_color"]
            )
        )
        self.content = QWidget(self)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
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
        self.indicator = HiddenStrip(self, ring=False) if dock.property("progressPanel") else None
        self.popup = None
        self.surface = None
        self.progress = 0.0
        self.expanding = False
        self.moving = False
        self.initializing = True
        self.relocating = False
        self.extents = {"width": 320, "height": 180}
        layout = saved_layout(manager, plugin_id)
        for key in self.extents:
            value = layout.get(key)
            if type(value) is int and 80 <= value <= 4096:
                self.extents[key] = value
        self.last_size = QSize(self.extents["width"], self.extents["height"])
        order = layout.get("order", len(collection.controllers))
        self.order = (
            order if type(order) is int and 0 <= order <= 10000 else len(collection.controllers)
        )
        self.area = (
            DOCK_AREAS["bottom"]
            if dock.property("progressPanel")
            else self.host.dockWidgetArea(dock)
        )
        dock.widget().grip.controller = self
        dock.widget().arrange(self.area)
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
        self.size_timer = QTimer(self)
        self.size_timer.setSingleShot(True)
        self.size_timer.timeout.connect(self.initialize_size)
        self.size_timer.start(0)

    def eventFilter(self, obj, event):
        if event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            surface = self.surface or self.dock.widget()
            if surface:
                surface.arrange(self.area)
        if (
            event.type() == QEvent.Type.Resize
            and not self.dock.isHidden()
            and not self.initializing
            and not self.relocating
        ):
            key = "height" if self.area == DOCK_AREAS["bottom"] else "width"
            self.extents[key] = self.dock.height() if key == "height" else self.dock.width()
            self.last_size = QSize(self.extents["width"], self.extents["height"])
        return False

    def location(self, area):
        if area != Qt.DockWidgetArea.NoDockWidgetArea:
            self.area = area
            surface = self.surface or self.dock.widget()
            surface.arrange(area)
            self.collection.layout_strips()

    def visibility(self, visible):
        if self.plugin_id in self.collection.controllers and not self.manager._panel_transition:
            self.collection.set_side_fixed(self, not self.dock.isHidden())
        if visible:
            self.collapse(immediate=True)
        self.collection.layout_strips()

    def current_extent(self):
        if self.dock.property("progressPanel"):
            return self.dock.property("compactHeight")
        return self.extents["height" if self.area == DOCK_AREAS["bottom"] else "width"]

    def restore_size(self):
        if not self.dock.isHidden():
            self.resize_extent(self.current_extent())

    def initialize_size(self):
        self.restore_size()
        self.initializing = False
        if self.dock.property("progressPanel"):
            self.extents["height"] = self.current_extent()
        self.remember_layout()

    def resize_extent(self, extent):
        if self.dock.property("progressPanel"):
            self.collection.layout_progress(self)
            return
        horizontal = self.area == DOCK_AREAS["bottom"]
        surface = self.surface or self.dock.widget()
        minimum = surface.minimumSizeHint()
        limit = (
            self.host.height() - self.host.title_bar.height() if horizontal else self.host.width()
        )
        smallest = max(80, minimum.height() if horizontal else minimum.width())
        extent = max(smallest, min(extent, max(smallest, limit - 120)))
        self.extents["height" if horizontal else "width"] = extent
        self.last_size = QSize(self.extents["width"], self.extents["height"])
        if self.popup:
            self.target = self.bounds()
            self.popup.content.setFixedSize(self.target.size())
            self.animate(self.progress)
        else:
            self.host.resizeDocks(
                [self.dock],
                [extent],
                Qt.Orientation.Vertical if horizontal else Qt.Orientation.Horizontal,
            )

    def remember_layout(self):
        ui = self.manager.preferences["ui"]
        if not isinstance(ui.get("panel_layouts"), dict):
            ui["panel_layouts"] = {}
        ui["panel_layouts"][self.plugin_id] = {
            "area": next(name for name, area in DOCK_AREAS.items() if area == self.area),
            **self.extents,
            "order": self.order,
        }
        self.manager._save()

    def pin(self):
        self.collection.set_side_fixed(self, True)
        self.collapse(immediate=True)
        self.dock.show()
        self.dock.raise_()
        self.restore_size()
        self.remember_layout()
        self.collection.layout_strips()

    def move_to(self, area):
        if area not in DOCK_AREAS.values() or not (self.dock.allowedAreas() & area):
            return
        if self.dock.property("progressPanel"):
            return
        self.collapse(immediate=True)
        hidden = self.dock.isHidden()
        transition = self.manager._panel_transition
        self.manager._panel_transition = True
        self.relocating = True
        peers = [
            c for c in self.collection.controllers.values() if c is not self and c.area == area
        ]
        if peers and area != self.area:
            hidden = peers[0].dock.isHidden()
            self.order = max(c.order for c in peers) + 1
        try:
            self.host.addDockWidget(area, self.dock)
            self.dock.setVisible(not hidden)
        finally:
            self.manager._panel_transition = transition
            self.relocating = False
        self.restore_size()
        self.collection.set_side_fixed(self, not hidden)
        self.remember_layout()
        self.collection.layout_strips()

    def begin_move(self):
        self.moving = True
        self.collapse(immediate=True)
        self.leave_timer.stop()

    def update_move(self, global_position):
        area = self.collection.edge_at(self.host.mapFromGlobal(global_position))
        if area and not (self.dock.allowedAreas() & area):
            area = None
        self.collection.show_drop_hint(area)

    def end_move(self, global_position):
        area = self.collection.edge_at(self.host.mapFromGlobal(global_position))
        self.collection.show_drop_hint(None)
        self.moving = False
        if area:
            self.move_to(area)
        self.collection.layout_strips()

    def show_menu(self, position):
        menu = QMenu(self.strip)
        menu.setStyleSheet(
            accent_style(PLUGIN_STYLE, COLORS["accent"], self.host.app_preferences["accent_color"])
        )
        hidden = self.dock.isHidden()
        menu.addAction(
            "靠边固定" if hidden else "自动隐藏", self.pin if hidden else self.dock.close
        )
        if not self.dock.property("progressPanel"):
            menu.addSeparator()
        for name, label in (("left", "停靠左侧"), ("right", "停靠右侧"), ("bottom", "停靠底部")):
            if self.dock.property("progressPanel"):
                break
            if not (self.dock.allowedAreas() & DOCK_AREAS[name]):
                continue
            action = menu.addAction(
                label, lambda checked=False, area=DOCK_AREAS[name]: self.move_to(area)
            )
            action.setCheckable(True)
            action.setChecked(self.area == DOCK_AREAS[name])
        menu.exec(position)
        menu.deleteLater()

    def bounds(self):
        if self.dock.property("progressPanel"):
            width = max(240, self.host.width() // 3)
            height = self.current_extent()
            return QRect(
                (self.host.width() - width) // 2, self.host.height() - height - 8, width, height
            )
        viewport = self.host.view.viewport()
        position = viewport.mapTo(self.host, QPoint())
        canvas = QRect(position, viewport.size())
        host = self.host.rect().adjusted(
            12, max(self.host.title_bar.height() + 10, canvas.top()), -12, -12
        )
        host.setBottom(self.host.height() - 1 - PANEL_BOTTOM_GAP)
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
        if self.moving or not self.dock.isHidden() or record is None or record.state != "enabled":
            return
        self.leave_timer.stop()
        if self.popup is None:
            self.collection.layout_strips()
            self.surface = self.dock.widget()
            self.surface.render_backdrop = False
            self.surface.setParent(None)
            self.dock.setWidget(None)
            self.popup = MorphPopup(self, self.surface)
            self.morph_origin = QRect(self.strip.geometry())
            self.target = self.bounds()
            self.popup.content.setFixedSize(self.target.size())
            self.popup.setGeometry(self.strip.geometry())
            self.surface.show()
            self.popup.show()
            self.popup.raise_()
            self.strip.raise_()
        self.start_animation(True)

    def start_animation(self, expanding):
        self.animation.stop()
        if not expanding and self.progress == 1.0:
            self.morph_origin = (
                self.collection.progress_ring_rect(self, resting=True)
                if self.dock.property("progressPanel")
                else QRect(self.strip.geometry())
            )
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
        start = self.morph_origin
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
        if self.dock.property("progressPanel"):
            self.collection.layout_strips()

    def schedule_collapse(self):
        if self.popup and self.expanding and not self.moving:
            self.leave_timer.start()

    def check_leave(self):
        if self.popup is None:
            return
        cursor = self.host.mapFromGlobal(QCursor.pos())
        popup_active = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if (
            self.popup.geometry().contains(cursor)
            or self.strip.geometry().contains(cursor)
            or self.strip.origin is not None
            or (
                self.indicator
                and (
                    self.indicator.geometry().contains(cursor) or self.indicator.origin is not None
                )
            )
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
        surface, popup = self.surface, self.popup
        # setWidget/show may synchronously emit visibilityChanged and reenter collapse.
        # Clear transient state first so ownership is restored exactly once.
        self.popup, self.surface = None, None
        self.progress = 0.0
        surface.setGraphicsEffect(None)
        surface.render_backdrop = True
        surface.setParent(self.dock)
        self.dock.setWidget(surface)
        surface.show()
        popup.hide()
        popup.deleteLater()

    def dispose(self):
        self.collapse(immediate=True)
        surface = self.dock.widget()
        if surface:
            surface.set_tabs([], self)
        self.animation.stop()
        self.leave_timer.stop()
        self.size_timer.stop()
        if self.moving:
            self.collection.show_drop_hint(None)
        self.strip.hide()
        self.strip.deleteLater()
        if self.indicator:
            self.indicator.hide()
            self.indicator.deleteLater()


class DockDropHint(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.setProperty("pluginSurface", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(colors_for(self)["accent"])
        color.setAlpha(145)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect(), 4, 4)


class PanelHovers(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.controllers = {}
        self.binding_side = False
        self.drop_hint = DockDropHint(host)
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.close_all()
            self.layout_strips()
        return False

    def layout_progress(self, controller):
        if not controller.dock.isHidden():
            controller.dock.setGeometry(controller.bounds())
            controller.dock.raise_()
        if controller.popup:
            controller.target = controller.bounds()
            controller.popup.content.setFixedSize(controller.target.size())
            controller.animate(controller.progress)

    def register(self, dock, plugin_id, manager):
        controller = HiddenPanel(self, dock, plugin_id, manager)
        peers = [c for c in self.controllers.values() if c.area == controller.area]
        self.controllers[plugin_id] = controller
        if peers and not dock.property("progressPanel"):
            self.set_side_fixed(controller, not peers[0].dock.isHidden())
        self.layout_strips()

    def set_side_fixed(self, source, fixed):
        if self.binding_side or source.manager._panel_transition:
            return
        self.binding_side = True
        try:
            for controller in tuple(self.controllers.values()):
                if controller.area != source.area:
                    continue
                if controller.dock.isHidden() == fixed:
                    controller.collapse(immediate=True)
                    controller.dock.setVisible(fixed)
                    if fixed:
                        controller.restore_size()
                controller.manager._remember_panel(controller.plugin_id)
        finally:
            self.binding_side = False

    def tab_drop_area(self, global_position):
        point = self.host.mapFromGlobal(global_position)
        for controller in self.controllers.values():
            surface = controller.dock.widget()
            if surface and surface.rail.isVisible() and surface.rail.geometry().contains(point):
                return controller.area
        area = self.edge_at(point)
        return area if area in (DOCK_AREAS["left"], DOCK_AREAS["right"]) else None

    def normalize_sides(self):
        """Migrate legacy/imported mixed modes without revealing fullscreen panels."""
        for area in (DOCK_AREAS["left"], DOCK_AREAS["right"]):
            group = sorted(
                (c for c in self.controllers.values() if c.area == area), key=lambda c: c.order
            )
            if not group:
                continue
            source = group[0]
            modes = source.manager.preferences["ui"].setdefault("panels", {})
            fixed = modes.get(source.plugin_id, not source.dock.isHidden())
            for controller in group:
                modes[controller.plugin_id] = fixed
            if not source.manager._fullscreen:
                self.set_side_fixed(source, fixed)

    def drop_tab(self, controller, global_position):
        area = self.tab_drop_area(global_position)
        if area is None or not (controller.dock.allowedAreas() & area):
            return
        # Capture the destination slot before moving/tabifying changes its geometry.
        before = None
        for peer in self.controllers.values():
            surface = peer.dock.widget()
            if peer.area == area and surface and surface.rail.isVisible():
                if surface.rail.geometry().contains(self.host.mapFromGlobal(global_position)):
                    local = surface.rail.mapFromGlobal(global_position)
                    before = next(
                        (
                            tab.target
                            for tab in surface.tabs.values()
                            if tab is not None and local.y() < tab.geometry().center().y()
                        ),
                        None,
                    )
                    break
        if controller.area != area:
            controller.move_to(area)
        group = sorted(
            (c for c in self.controllers.values() if c.area == area), key=lambda c: c.order
        )
        if before is not controller:
            group.remove(controller)
            group.insert(group.index(before) if before in group else len(group), controller)
        for index, item in enumerate(group):
            item.order = index
            item.remember_layout()
        self.layout_strips()
        if not controller.dock.isHidden():
            self.activate_tab(controller)

    def unregister(self, plugin_id):
        controller = self.controllers.pop(plugin_id, None)
        if controller:
            controller.dispose()
            self.layout_strips()

    def close_all(self):
        self.show_drop_hint(None)
        for controller in self.controllers.values():
            controller.collapse(immediate=True)

    def edge_at(self, position):
        if not self.host.rect().contains(position) or position.y() < self.host.title_bar.height():
            return None
        distances = {
            DOCK_AREAS["left"]: position.x(),
            DOCK_AREAS["right"]: self.host.width() - 1 - position.x(),
            DOCK_AREAS["bottom"]: self.host.height() - 1 - position.y(),
        }
        area = min(distances, key=distances.get)
        return area if distances[area] <= 72 else None

    def show_drop_hint(self, area):
        if not area:
            self.drop_hint.hide()
            return
        top, width, height = self.host.title_bar.height() + 6, self.host.width(), self.host.height()
        if area == DOCK_AREAS["bottom"]:
            rect = QRect(8, height - 14, width - 16, 6)
        else:
            rect = QRect(8 if area == DOCK_AREAS["left"] else width - 14, top, 6, height - top - 8)
        self.drop_hint.setGeometry(rect)
        self.drop_hint.show()
        self.drop_hint.raise_()

    def update_progress_ring(self):
        for controller in self.controllers.values():
            if controller.dock.property("progressPanel"):
                host = self.host
                index = host.path_positions.get(host.current_path, -1)
                position = f"{index + 1 if index >= 0 else 0}/{len(host.paths)}"
                controller.strip.setToolTip(f"当前图片 {position} · 悬停展开，点击固定")
                controller.strip.update()

    def progress_ring_rect(self, controller, *, resting=False):
        preview = controller.dock.property("previewGeometry")
        if isinstance(preview, QRect) and not preview.isEmpty():
            center = preview.center().y()
            if resting:
                center = self.host.height() - 8 - preview.height() + (preview.height() - 1) // 2
            return QRect(
                max(0, preview.left() - RING_SIZE - 8),
                center - (RING_SIZE - 1) // 2,
                RING_SIZE,
                RING_SIZE,
            )
        bottom = self.host.height() - RING_SIZE - 14
        if controller.popup and not resting:
            bottom -= round((controller.current_extent() + 8) * controller.progress)
        return QRect((self.host.width() - RING_SIZE) // 2, bottom, RING_SIZE, RING_SIZE)

    def layout_strips(self):
        if getattr(self, "laying_out", False):
            return
        self.laying_out = True
        try:
            self._layout_strips()
        finally:
            self.laying_out = False

    def activate_tab(self, controller):
        for other in self.controllers.values():
            if other.area == controller.area and other is not controller:
                other.collapse(immediate=True)
        if controller.dock.isHidden():
            controller.reveal()
        else:
            controller.dock.raise_()
        self.layout_strips()

    def layout_tabs(self):
        groups = {}
        for controller in self.controllers.values():
            if controller.area == DOCK_AREAS["bottom"]:
                continue
            record = controller.manager.records.get(controller.plugin_id)
            if record is not None and record.state == "enabled":
                groups.setdefault(controller.area, []).append(controller)
        for controllers in groups.values():
            controllers.sort(key=lambda c: c.order)
            fixed = [c for c in controllers if not c.dock.isHidden()]
            if len(fixed) > 1:
                first = fixed[0].dock
                for controller in fixed[1:]:
                    if controller.dock not in self.host.tabifiedDockWidgets(first):
                        self.host.tabifyDockWidget(first, controller.dock)
            for controller in controllers:
                surface = controller.surface or controller.dock.widget()
                surface.set_tabs(
                    fixed if len(fixed) > 1 and not controller.dock.isHidden() else [], controller
                )
        # Qt still owns tab selection/stack geometry; its native bottom tabs take no space.
        for bar in self.host.findChildren(
            QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly
        ):
            # Hidden native tabs still reserve their styled size hint without this.
            bar.setStyleSheet(
                "QTabBar { min-height: 0; max-height: 0; padding: 0; margin: 0; border: 0; }"
                "QTabBar::tab { height: 0; min-height: 0; max-height: 0;"
                " padding: 0; margin: 0; border: 0; }"
            )
            bar.setFixedHeight(0)
            bar.hide()

    def _layout_strips(self):
        self.layout_tabs()
        areas = {}
        for controller in self.controllers.values():
            if controller.dock.property("progressPanel"):
                self.layout_progress(controller)
            record = controller.manager.records.get(controller.plugin_id)
            hidden = controller.dock.isHidden() and record is not None and record.state == "enabled"
            controller.strip.setVisible(hidden and self.host.isVisible())
            if controller.indicator:
                controller.indicator.setVisible(hidden and self.host.isVisible())
                controller.indicator.setGeometry(
                    (self.host.width() - 84) // 2, self.host.height() - 9, 84, 5
                )
                controller.indicator.raise_()
            if hidden:
                areas.setdefault(controller.area, []).append(controller)
        for area, controllers in areas.items():
            controllers.sort(key=lambda c: c.order)
            for index, controller in enumerate(controllers):
                offset = (index - (len(controllers) - 1) / 2) * 96
                if controller.dock.property("progressPanel"):
                    rect = self.progress_ring_rect(controller)
                elif area == Qt.DockWidgetArea.BottomDockWidgetArea:
                    rect = QRect(
                        round(self.host.width() / 2 - 42 + offset), self.host.height() - 9, 84, 5
                    )
                else:
                    x = 4 if area == Qt.DockWidgetArea.LeftDockWidgetArea else self.host.width() - 9
                    rect = QRect(x, round(self.host.height() / 2 - 42 + offset), 5, 84)
                controller.strip.setGeometry(rect)
                controller.strip.raise_()
