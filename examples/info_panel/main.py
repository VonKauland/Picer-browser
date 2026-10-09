"""A single dockable panel, owned and cleaned up by the host."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class Plugin:
    def activate(self, context):
        self.context = context
        panel = QWidget()
        panel.setMinimumWidth(180)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        self.label = QLabel("打开图片后查看信息")
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.label)
        layout.addStretch()
        context.add_panel(panel, area="right")
        context.subscribe("image.changed", self.update)
        path = context.current_path()
        if path:
            image = context.image()
            self.label.setText(f"{path.name}\n\n{image.width()} × {image.height()}")

    def update(self, event):
        name = event.path.name if event.path else "尚未打开图片"
        self.label.setText(f"{name}\n\n{event.width} × {event.height}")
