"""Panel-local wheel gestures, without changing navigation or image zoom."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)


class ParentEntry(QPushButton):
    activated = Signal()

    def __init__(self):
        super().__init__("..  上层文件夹")
        self.setObjectName("parentEntry")
        self.setCheckable(True)
        self.setFixedHeight(38)
        self.base_style = """
QPushButton#parentEntry { text-align: left; background: transparent; padding: 6px;
border: 1px solid transparent; border-radius: 9px; }
QPushButton#parentEntry:hover { background: #343437; }
QPushButton#parentEntry:checked { background: #414145; border-color: #E8FF59; }
"""
        self.set_accent("#E8FF59")

    def set_accent(self, color):
        self.setStyleSheet(self.base_style.replace("#E8FF59", color))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class BrowserPanel(QWidget):
    def __init__(self, resize_icons, up, back, forward, context):
        super().__init__()
        self.resize_icons = resize_icons
        self.up, self.back, self.forward = up, back, forward
        self.context = context
        self.wheel_remainder = 0
        self.scroll_remainder = 0
        QApplication.instance().installEventFilter(self)

    def stop(self):
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, watched, event):
        if not isinstance(watched, QWidget) or not (watched is self or self.isAncestorOf(watched)):
            return False
        editing = isinstance(
            watched, (QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QAbstractSpinBox)
        )
        focused = QApplication.focusWidget()
        editing |= isinstance(
            focused, (QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QAbstractSpinBox)
        ) and self.isAncestorOf(focused)
        if (
            editing
            and event.type() == QEvent.Type.ShortcutOverride
            and self.context.handle_browser_key(event)
        ):
            # Prevent the window QAction from stealing editable Enter/Backspace
            # (including their user-remapped versions), then keep native KeyPress.
            return True
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton):
                if event.type() == QEvent.Type.MouseButtonRelease:
                    (self.back if event.button() == Qt.MouseButton.BackButton else self.forward)()
                event.accept()
                return True
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and not editing:
            if self.context.handle_browser_key(event):
                return True
        if event.type() == QEvent.Type.Wheel:
            if not watched.property("browserViewport"):
                return False
            focused = QApplication.focusWidget()
            active = focused is self or (focused is not None and self.isAncestorOf(focused))
            if active and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Angle wheels accumulate partial notches; precision touchpads
                # use pixel deltas. A complete notch changes the size by 4 px.
                delta, threshold = event.angleDelta().y(), 120
                if not delta:
                    delta, threshold = event.pixelDelta().y(), 30
                self.wheel_remainder += delta
                steps = int(self.wheel_remainder / threshold)
                self.wheel_remainder -= steps * threshold
                if steps:
                    self.resize_icons(steps)
                if event.phase() == Qt.ScrollPhase.ScrollEnd:
                    self.wheel_remainder = 0
                event.accept()
                return True
            self.wheel_remainder = 0
            if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                view = watched.parentWidget()
                amount = -event.angleDelta().y() / 120 * max(180, view.iconSize().height() * 3)
                if event.pixelDelta().y():
                    amount = -event.pixelDelta().y() * 2
                self.scroll_remainder += amount
                pixels = int(self.scroll_remainder)
                self.scroll_remainder -= pixels
                bar = view.verticalScrollBar()
                bar.setValue(bar.value() + pixels)
                event.accept()
                return True
        return super().eventFilter(watched, event)
