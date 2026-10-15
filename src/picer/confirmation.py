"""A themed confirmation with cancellation as the default action."""

from PySide6.QtWidgets import QDialog

from picer.messages import MessageDialog


class Confirmation(MessageDialog):
    def __init__(self, parent, title, message, action):
        super().__init__(parent, title, message, kind="question", action=action)


def confirm(parent, title, message, action="确认恢复"):
    dialog = Confirmation(parent, title, message, action)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return accepted
