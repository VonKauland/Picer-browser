"""Host-owned message dialogs with shared chrome and frosted accent artwork."""

from functools import lru_cache

from PIL import Image, ImageFilter
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)
from PySide6.QtWidgets import (
    QMessageBox as NativeMessageBox,
)

from picer.host_style import mark_host, scope_style
from picer.theme import COLORS, STYLE, accent_style
from picer.ui import StyledDialog, colors_for


@lru_cache(maxsize=32)
def frosted_icon(kind, accent):
    """Render at 3x; blur only the rear layer underneath the translucent pane."""
    size = 240
    rear = QImage(size, size, QImage.Format.Format_RGBA8888)
    rear.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rear)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    painter.translate(35, 33)
    painter.rotate(-8)
    painter.setPen(QPen(QColor(accent), 2.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(-23, -23, 46, 46), 9, 9)
    painter.end()
    blurred = Image.frombytes("RGBA", (size, size), bytes(rear.constBits())).filter(
        ImageFilter.GaussianBlur(10)
    )
    blur = QImage(blurred.tobytes(), size, size, QImage.Format.Format_RGBA8888).copy()
    result = rear.copy()
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    painter.translate(49, 49)
    painter.rotate(7)
    pane = QPainterPath()
    pane.addRoundedRect(QRectF(-24, -24, 48, 48), 9, 9)
    painter.fillPath(pane.translated(0, 2), QColor(0, 0, 0, 45))
    painter.save()
    painter.setClipPath(pane)
    # Map the blurred rear back through the pane's local transform.
    transform = painter.worldTransform()
    painter.resetTransform()
    painter.drawImage(0, 0, blur)
    painter.setWorldTransform(transform)
    painter.fillPath(pane, QColor(120, 124, 126, 160))
    frost = QLinearGradient(-24, -24, 24, 24)
    frost.setColorAt(0, QColor(255, 255, 255, 170))
    frost.setColorAt(0.42, QColor(222, 225, 226, 35))
    frost.setColorAt(1, QColor(235, 240, 242, 90))
    painter.fillPath(pane, frost)
    painter.restore()
    edge = QColor(accent)
    edge.setAlpha(170)
    painter.setPen(QPen(edge, 0.8))
    painter.drawPath(pane)
    painter.setPen(QPen(QColor(accent), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if kind in ("question", "warning"):
        font = painter.font()
        font.setPixelSize(31)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(-20, -22, 40, 44),
            Qt.AlignmentFlag.AlignCenter,
            "?" if kind == "question" else "!",
        )
    elif kind == "critical":
        painter.drawLine(-8, -8, 8, 8)
        painter.drawLine(-8, 8, 8, -8)
    else:
        painter.drawLine(-11, 0, -3, 8)
        painter.drawLine(-3, 8, 12, -9)
    painter.end()
    return result


class PromptIcon(QWidget):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(80, 80)
        self.setAccessibleName(
            {"question": "询问", "warning": "提醒", "critical": "错误", "information": "成功"}[kind]
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), frosted_icon(self.kind, colors_for(self)["accent"]))


class MessageDialog(StyledDialog):
    def __init__(self, parent, title, message, *, kind="warning", action=None):
        super().__init__(title, parent=parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        if (
            parent is not None
            and parent.window().windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        ):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        # Explicit host style also covers startup errors before MainWindow exists.
        self.setStyleSheet(
            scope_style(accent_style(STYLE, COLORS["accent"], colors_for(self)["accent"]))
        )
        self.setMinimumWidth(460)
        self.resize(560, 240)
        row = QHBoxLayout()
        row.setSpacing(20)
        self.icon = PromptIcon(kind)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.message = QLabel(message)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.message, 1)
        self.body.addLayout(row, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = None
        if action is not None:
            self.cancel_button = QPushButton("取消")
            self.cancel_button.setDefault(True)
            self.cancel_button.clicked.connect(self.reject)
            buttons.addWidget(self.cancel_button)
        self.confirm_button = QPushButton(action or "我知道了")
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.setAutoDefault(action is None)
        self.confirm_button.setDefault(action is None)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.confirm_button)
        self.body.addLayout(buttons)
        mark_host(self)
        (self.cancel_button or self.confirm_button).setFocus()


class MessageBox:
    """Keep existing StandardButton results and monkeypatchable call sites."""

    StandardButton = NativeMessageBox.StandardButton

    @staticmethod
    def _show(parent, title, message, kind, action=None):
        dialog = MessageDialog(parent, title, message, kind=kind, action=action)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return (
                (MessageBox.StandardButton.Yes if accepted else MessageBox.StandardButton.No)
                if action
                else MessageBox.StandardButton.Ok
            )
        finally:
            dialog.deleteLater()

    @staticmethod
    def question(parent, title, message, buttons=None, defaultButton=None):
        action = "覆盖绑定" if title == "快捷键冲突" else "卸载" if title == "卸载组件" else "确认"
        return MessageBox._show(parent, title, message, "question", action)

    @staticmethod
    def warning(parent, title, message):
        return MessageBox._show(parent, title, message, "warning")

    @staticmethod
    def critical(parent, title, message):
        return MessageBox._show(parent, title, message, "critical")

    @staticmethod
    def information(parent, title, message):
        return MessageBox._show(parent, title, message, "information")
