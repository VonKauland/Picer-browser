"""Own held navigation timing independently of the operating system repeat rate."""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)


class NavigationKeys(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.held = None
        self.direction = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.repeat)
        QApplication.instance().installEventFilter(self)
        host.previous_action.setAutoRepeat(False)
        host.next_action.setAutoRepeat(False)

    def stop(self):
        self.timer.stop()
        self.held = None
        self.host.loader.set_rapid(False)

    def repeat(self):
        if self.allowed_focus():
            self.host.navigate(self.direction)
        else:
            self.stop()

    def allowed_focus(self):
        if (
            not self.host.isActiveWindow()
            or QApplication.activeModalWidget()
            or QApplication.activePopupWidget()
        ):
            return False
        focus = QApplication.focusWidget()
        while focus and focus is not self.host:
            if isinstance(
                focus,
                (
                    QLineEdit,
                    QPlainTextEdit,
                    QTextEdit,
                    QAbstractSpinBox,
                    QComboBox,
                    QAbstractItemView,
                ),
            ):
                return False
            focus = focus.parentWidget()
        return focus is self.host or focus is None

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate):
            if obj is self.host or kind == QEvent.Type.ApplicationDeactivate:
                self.stop()
            return False
        if kind not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if kind == QEvent.Type.KeyRelease and self.held == event.key():
            if not event.isAutoRepeat():
                self.stop()
            return True
        if not self.allowed_focus():
            return False
        sequence = QKeySequence(event.keyCombination())
        direction = next(
            (
                offset
                for offset, action in ((-1, self.host.previous_action), (1, self.host.next_action))
                if action.isEnabled() and sequence == action.shortcut()
            ),
            0,
        )
        if not direction:
            return False
        event.accept()
        if kind == QEvent.Type.KeyPress and not event.isAutoRepeat() and self.held != event.key():
            self.held, self.direction = event.key(), direction
            self.host.loader.set_rapid(True)
            self.host.navigate(direction)
            self.timer.start(self.host.app_preferences["key_repeat_ms"])
        return True

    def dispose(self):
        self.stop()
        QApplication.instance().removeEventFilter(self)
