"""Small text-only, click-through frosted notifications with translation motion."""

from collections import deque

from PIL import Image, ImageFilter
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect

from picer.i18n import tr
from picer.panels import GlassSurface


class NotificationBubble(GlassSurface):
    def __init__(self, host):
        super().__init__(host.glass, host, radius=16)
        # Blur only this small region; notifications never activate full-window glass.
        self.render_backdrop = False
        self.host = host
        self.message = ""
        self.pending = deque(maxlen=5)
        self.phase = "hidden"
        self.progress = 0.0
        self.closed = False
        self.snapshot = QImage()
        self.setFixedHeight(32)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(tr("操作通知"))
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 65))
        self.setGraphicsEffect(shadow)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(140)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.advance)
        self.motion.finished.connect(self.finished)
        self.observed_parent = host
        host.installEventFilter(self)
        host.title_bar.installEventFilter(self)
        self.hide()

    def uses_glass(self):
        # Notification glass is independent of the panel appearance preference.
        return True

    def notify(self, message):
        message = " ".join(str(message).split())[:160]
        if self.closed or not message:
            return
        if self.phase != "hidden":
            if message != self.message and (not self.pending or self.pending[-1] != message):
                self.pending.append(message)
            return
        self.present(message)

    def present(self, message):
        parent = QApplication.activeModalWidget() or self.host
        if parent is not self.parentWidget():
            self.observed_parent.removeEventFilter(self)
            self.setParent(parent)
            parent.installEventFilter(self)
            self.observed_parent = parent
        self.message = message
        self.setAccessibleDescription(message)
        self.setFixedWidth(min(self.fontMetrics().horizontalAdvance(message) + 32, 360))
        top = 12
        if parent is self.host:
            top += max(0, self.host.title_bar.y() + self.host.title_bar.height())
        region = QRect((parent.width() - self.width()) // 2, top, self.width(), self.height())
        pixels = parent.grab(region).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        blurred = Image.frombytes("RGBA", (pixels.width(), pixels.height()), bytes(pixels.bits()))
        blurred = blurred.filter(ImageFilter.GaussianBlur(6))
        self.snapshot = QImage(
            blurred.tobytes(), blurred.width, blurred.height, QImage.Format.Format_RGBA8888
        ).copy()
        self.phase = "entering"
        self.progress = 0.0
        self.reposition()
        self.show()
        self.raise_()
        self.backdrop.invalidate()
        self.animate(1.0)

    def animate(self, target):
        self.motion.stop()
        self.motion.setStartValue(self.progress)
        self.motion.setEndValue(target)
        self.motion.start()

    def advance(self, value):
        self.progress = float(value)
        self.reposition()

    def reposition(self):
        parent = self.parentWidget()
        top = 12
        if parent is self.host:
            top += max(0, self.host.title_bar.y() + self.host.title_bar.height())
        y = round(-self.height() + (top + self.height()) * self.progress)
        self.move((parent.width() - self.width()) // 2, y)

    def finished(self):
        if self.phase == "entering":
            self.phase = "visible"
            self.timer.start(self.host.app_preferences["notification_ms"])
        elif self.phase == "leaving":
            self.hide()
            self.phase = "hidden"
            if self.pending:
                self.present(self.pending.popleft())

    def dismiss(self):
        if self.phase in {"entering", "visible"}:
            self.timer.stop()
            self.phase = "leaving"
            self.animate(0.0)

    def eventFilter(self, obj, event):
        if (
            obj is self.observed_parent
            and obj is not self.host
            and event.type() == QEvent.Type.Hide
        ):
            obj.removeEventFilter(self)
            self.setParent(self.host)
            self.observed_parent = self.host
            self.host.installEventFilter(self)
            if self.phase != "hidden" and not self.closed:
                self.reposition()
                self.show()
                self.raise_()
        if event.type() in {QEvent.Type.Resize, QEvent.Type.Move} and self.isVisible():
            self.reposition()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        painter.setClipPath(path)
        if not self.snapshot.isNull():
            painter.drawImage(self.rect(), self.snapshot)
        painter.fillPath(path, QColor(38, 38, 40, 165))
        painter.setPen(QColor("#F3F3F0"))
        text = self.fontMetrics().elidedText(
            self.message, Qt.TextElideMode.ElideRight, self.width() - 32
        )
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def dispose(self):
        self.closed = True
        self.timer.stop()
        self.motion.stop()
        self.pending.clear()
        self.hide()
        self.backdrop.surfaces.discard(self)
        self.observed_parent.removeEventFilter(self)
        self.host.title_bar.removeEventFilter(self)
