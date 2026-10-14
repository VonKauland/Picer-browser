"""A themed confirmation with cancellation as the default action."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton

from picer.ui import StyledDialog


class Confirmation(StyledDialog):
    def __init__(self, parent, title, message, action):
        super().__init__(title, "", parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        if parent.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(440)
        self.resize(480, 230)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setObjectName("muted")
        self.body.addWidget(text)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton(action)
        self.confirm_button.setObjectName("primaryButton")
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.confirm_button)
        self.body.addLayout(row)
        self.cancel_button.setFocus()


def confirm(parent, title, message, action="确认恢复"):
    dialog = Confirmation(parent, title, message, action)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return accepted
