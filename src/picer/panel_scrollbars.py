"""One preference for panel scrollbars, including lazily created plugin views."""

from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractScrollArea, QApplication


class PanelScrollbars(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.original = WeakKeyDictionary()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if isinstance(obj, QAbstractScrollArea) and event.type() in (
            QEvent.Type.Polish,
            QEvent.Type.Show,
            QEvent.Type.ParentChange,
        ):
            self.timer.start(0)
        return False

    def refresh(self):
        visible = self.host.app_preferences["panel_scrollbars"]
        for area in self.host.findChildren(QAbstractScrollArea):
            parent = area
            while parent is not None and parent is not self.host:
                if parent.property("pluginSurface"):
                    break
                parent = parent.parentWidget()
            if parent is None or parent is self.host:
                continue
            if area not in self.original:
                self.original[area] = (
                    area.horizontalScrollBarPolicy(),
                    area.verticalScrollBarPolicy(),
                )
            horizontal, vertical = self.original[area]
            area.setHorizontalScrollBarPolicy(
                horizontal if visible else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            area.setVerticalScrollBarPolicy(
                vertical if visible else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )

    def dispose(self):
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
