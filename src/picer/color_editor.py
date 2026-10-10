"""An explicit-save accent editor with a hex field and native-independent picker."""

import re

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget

from picer.host_style import mark_host
from picer.theme import COLORS


def valid_accent(value):
    return isinstance(value, str) and (not value or bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value)))


class ColorEditor(QWidget):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.text = QLineEdit()
        self.text.setMaxLength(7)
        self.text.setFixedWidth(150)
        self.text.setPlaceholderText("跟随皮肤")
        self.text.setAccessibleName("强调色十六进制色值")
        self.button = QPushButton("选择颜色")
        self.button.clicked.connect(self.choose)
        self.text.textChanged.connect(self.refresh)
        row.addWidget(self.text)
        row.addWidget(self.button)
        self.setValue(value)

    def setValue(self, value):
        self.text.setText(value)
        self.refresh()

    def value(self):
        value = self.text.text().strip()
        if not valid_accent(value):
            raise ValueError("强调色请输入 #RRGGBB 色值，或留空跟随皮肤。")
        return value.upper()

    def refresh(self):
        value = self.text.text().strip()
        color = QColor(value if value and valid_accent(value) else COLORS["accent"])
        text = "#242426" if color.lightnessF() > 0.5 else "#F3F3F0"
        self.button.setStyleSheet(f"QPushButton {{ background: {color.name()}; color: {text}; }}")

    def choose(self):
        value = self.text.text().strip()
        dialog = QColorDialog(
            QColor(value if valid_accent(value) and value else COLORS["accent"]), self
        )
        dialog.setWindowTitle("选择强调色")
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        mark_host(dialog)
        dialog.setStyleSheet("QColorDialog { background: #242426; }")
        if dialog.exec() == QColorDialog.DialogCode.Accepted:
            self.setValue(dialog.selectedColor().name().upper())
        dialog.deleteLater()
