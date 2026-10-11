"""A fullscreen title bar that slides over the canvas without reserving space."""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QApplication, QWidget


class FullscreenChrome(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.bar = host.title_bar
        self.slot = host.menuWidget()
        self.revealed = False
        self.animation = QPropertyAnimation(self.bar, b"pos", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.leave = QTimer(self)
        self.leave.setSingleShot(True)
        self.leave.setInterval(220)
        self.leave.timeout.connect(self.hide_if_outside)
        self.edge = QWidget(host)
        self.edge.setMouseTracking(True)
        self.edge.hide()
        self.bar.setMouseTracking(True)
        host.view.viewport().setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

    def sync(self):
        self.animation.stop()
        self.leave.stop()
        self.revealed = False
        if self.host.isFullScreen():
            self.slot.setFixedHeight(0)
            self.bar.setParent(self.host)
            self.bar.move(0, -48)
            self.bar.show()
            self.edge.show()
        else:
            self.edge.hide()
            self.bar.setParent(self.slot)
            self.slot.setFixedHeight(48)
            self.bar.move(0, 0)
            self.bar.show()
        self.arrange()
        if hasattr(self.host, "panel_hovers"):
            self.host.panel_hovers.layout_strips()

    def arrange(self):
        self.bar.resize(self.host.width(), 48)
        self.edge.setGeometry(0, 0, self.host.width(), 2)
        self.bar.raise_()
        self.edge.raise_()

    def reveal(self, visible):
        if not self.host.isFullScreen() or visible == self.revealed:
            return
        self.revealed = visible
        self.animation.stop()
        self.bar.raise_()
        self.animation.setStartValue(self.bar.pos())
        self.animation.setEndValue(QPoint(0, 0 if visible else -48))
        self.animation.start()

    def hide_if_outside(self):
        if QApplication.activePopupWidget() or QApplication.activeModalWidget():
            self.leave.start()
            return
        from PySide6.QtGui import QCursor

        point = self.host.mapFromGlobal(QCursor.pos())
        if not self.host.rect().contains(point) or point.y() >= 48:
            self.reveal(False)

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.host and kind == QEvent.Type.Resize:
            self.arrange()
        if not self.host.isFullScreen():
            return False
        if isinstance(obj, QWidget) and QWidget.window(obj) is self.host:
            if kind in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                from PySide6.QtGui import QCursor

                point = self.host.mapFromGlobal(QCursor.pos())
                if kind == QEvent.Type.MouseMove:
                    point = self.host.mapFromGlobal(event.globalPosition().toPoint())
                if 0 <= point.y() < 2:
                    self.leave.stop()
                    self.reveal(True)
                elif self.revealed and point.y() >= 48:
                    if not self.leave.isActive():
                        self.leave.start()
                else:
                    self.leave.stop()
        return False

    def dispose(self):
        self.animation.stop()
        self.leave.stop()
        QApplication.instance().removeEventFilter(self)
