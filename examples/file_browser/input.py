"""Panel-local wheel gestures, without changing navigation or image zoom."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget


class BrowserPanel(QWidget):
    def __init__(self, resize_icons):
        super().__init__()
        self.resize_icons = resize_icons
        self.wheel_remainder = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
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
        return super().eventFilter(watched, event)
