"""Application startup, including a bounded CI smoke test."""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from windows_tool.window import MainWindow


def main() -> int:
    """Start the GUI; --smoke-test verifies the packaged application in CI."""
    smoke_test = "--smoke-test" in sys.argv[1:]
    app = QApplication([sys.argv[0]] if smoke_test else sys.argv)
    app.setApplicationName("WindowsTool")
    window = MainWindow()
    window.show()

    if smoke_test:

        def verify() -> None:
            window.action_button.click()
            passed = (
                window.isVisible()
                and window.click_count == 1
                and window.feedback_label.text() == "Button clicked 1 time(s)."
            )
            app.exit(0 if passed else 1)

        QTimer.singleShot(0, verify)
        QTimer.singleShot(10_000, lambda: app.exit(2))

    return app.exec()
