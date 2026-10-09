"""Main window and its interaction."""

from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    """Show click feedback without blocking the event loop."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WindowsTool")
        self.resize(480, 240)
        self.click_count = 0

        self.feedback_label = QLabel("Ready. Click the button below.")
        self.action_button = QPushButton("Click me")
        self.action_button.clicked.connect(self.on_button_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.feedback_label)
        layout.addWidget(self.action_button)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def on_button_clicked(self) -> None:
        """Update visible feedback for every click."""
        self.click_count += 1
        self.feedback_label.setText(f"Button clicked {self.click_count} time(s).")
