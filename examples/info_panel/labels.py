"""Wrapping metadata cells with no minimum column width."""

from PySide6.QtCore import QSize, Qt
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

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def sizeHint(self):
        width = min(140, super().sizeHint().width())
        return QSize(width, self.heightForWidth(width))
