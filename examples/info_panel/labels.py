"""Wrapping metadata cells with no minimum column width."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class DetailLabel(QLabel):
    """Let long paths and metadata wrap rather than impose a minimum column width."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sync_height(self):
        # Font/style propagation can invalidate QFormLayout's cached row height
        # after it has already placed a cell. Enforce the current wrapped height.
        if self.width() > 0:
            height = self.heightForWidth(self.width())
            if height > 0 and self.minimumHeight() != height:
                self.setMinimumHeight(height)

    def setText(self, text):
        super().setText(text)
        self.sync_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.sync_height()

    def minimumSizeHint(self):
        # QLabel includes style/leading in its height hint, beyond fontMetrics.
        # Discard only the minimum width so narrow forms never crop a text row.
        return QSize(0, max(self.fontMetrics().height(), super().minimumSizeHint().height()))

    def sizeHint(self):
        width = min(140, super().sizeHint().width())
        return QSize(width, self.heightForWidth(width))
