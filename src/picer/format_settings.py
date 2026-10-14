"""Format selection and explicit per-user Windows integration controls."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from picer.imaging import RAW_SUFFIXES, supported_suffixes
from picer.ui import Card, Toggle
from picer.windows_integration import WindowsIntegration, open_default_apps


class FormatSelection(QWidget):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        self.unknown = []
        for group, extensions in (
            ("常用与其他图片", supported_suffixes() - RAW_SUFFIXES),
            ("相机 RAW", RAW_SUFFIXES),
        ):
            row = layout.rowCount()
            layout.addWidget(QLabel(group), row, 0, 1, 3)
            for index, suffix in enumerate(sorted(extensions)):
                button = Toggle()
                button.setAccessibleName("允许读取 " + suffix[1:].upper())
                item = QWidget()
                line = QHBoxLayout(item)
                line.setContentsMargins(0, 4, 8, 4)
                line.addWidget(QLabel(suffix[1:].upper()))
                line.addStretch()
                line.addWidget(button)
                layout.addWidget(item, row + 1 + index // 3, index % 3)
                self.buttons[suffix] = button
        self.setValue(value)

    def value(self):
        selected = sorted(s for s, button in self.buttons.items() if button.isChecked())
        return (
            None
            if len(selected) == len(self.buttons) and not self.unknown
            else sorted(selected + self.unknown)
        )

    def setValue(self, value):
        self.unknown = [s for s in (value or []) if s not in self.buttons]
        for suffix, button in self.buttons.items():
            button.setChecked(value is None or suffix in value)


def build_format_page(dialog, layout):
    card = Card("可读取的图片格式")
    note = QLabel("只显示当前解码器支持的格式。取消勾选后，打开、拖入和文件夹浏览将跳过该格式。")
    note.setWordWrap(True)
    note.setObjectName("muted")
    card.body.addWidget(note)
    selection = FormatSelection(dialog.values["readable_formats"])
    dialog.editors["readable_formats"] = selection
    row = QHBoxLayout()
    for label, value in (("全选", None), ("清空", [])):
        button = QPushButton(label)
        button.clicked.connect(lambda checked=False, value=value: selection.setValue(value))
        row.addWidget(button)
    row.addStretch()
    card.body.addLayout(row)
    card.body.addWidget(selection)
    layout.addWidget(card)
    card = Card("Windows 系统集成")
    status = QLabel("先应用格式选择，再使用下方按钮。注册仅影响当前 Windows 用户，无需管理员权限。")
    status.setWordWrap(True)
    status.setObjectName("muted")
    card.body.addWidget(status)

    def execute(operation):
        from picer.formats import enabled_formats
        from picer.preferences import read_preferences

        try:
            if (
                operation != "remove"
                and selection.value() != read_preferences(dialog.manager)["readable_formats"]
            ):
                raise ValueError("格式选择尚未应用，请先点击底部的「应用」。")
            integration = WindowsIntegration()
            suffixes = enabled_formats(read_preferences(dialog.manager))
            if operation == "default":
                integration.register_viewer(suffixes)
                open_default_apps()
                status.setText("已注册揽映。请在 Windows 默认应用设置中确认格式关联。")
            elif operation == "register":
                integration.register_context_menu(suffixes)
                status.setText("已注册「使用揽映打开」。Windows 11 中可在「显示更多选项」里找到。")
            else:
                integration.remove_context_menu()
                status.setText("已移除「使用揽映打开」入口。")
        except (OSError, ValueError) as error:
            status.setText(str(error))

    for label, operation in (
        ("设为 Windows 默认图片浏览器…", "default"),
        ("注册 Windows 右键菜单", "register"),
        ("移除 Windows 右键菜单", "remove"),
    ):
        button = QPushButton(label)
        button.setEnabled(sys.platform == "win32")
        button.clicked.connect(lambda checked=False, operation=operation: execute(operation))
        card.body.addWidget(button)
    note = QLabel("Windows 保护默认应用关联，需要在系统设置中确认。移动应用文件夹后请重新注册。")
    note.setWordWrap(True)
    note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    card.body.addWidget(note)
    layout.addWidget(card)
