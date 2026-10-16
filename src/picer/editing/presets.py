"""Named, bounded editor recipes shared by the dropdown and plugin settings."""

import copy

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from picer.editing.engine import validate
from picer.host_style import mark_host
from picer.ui import StyledDialog


def read_presets(context):
    values = context.get_setting("presets", [])
    result = []
    if not isinstance(values, list):
        return result
    for entry in values[:64]:
        try:
            name = entry["name"].strip()
            if not name or len(name) > 48 or any(row["name"] == name for row in result):
                continue
            result.append({"name": name, "state": validate(entry["state"])})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return result


class PresetDialog(StyledDialog):
    def __init__(self, names, parent):
        super().__init__("新增预设", parent=parent)
        self.resize(400, 220)
        self.names = names
        self.body.addWidget(QLabel("将当前修改参数保存为预设"))
        self.name = QLineEdit()
        self.name.setMaxLength(48)
        self.name.setPlaceholderText("预设名称")
        self.body.addWidget(self.name)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.body.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.confirm = QPushButton("确认新增")
        self.confirm.setObjectName("primaryButton")
        self.confirm.clicked.connect(self.accept)
        row.addWidget(self.confirm)
        self.body.addLayout(row)
        self.name.textChanged.connect(self.check)
        self.check()
        self.name.setFocus()
        mark_host(self)

    def check(self):
        text = self.name.text().strip()
        self.confirm.setEnabled(bool(text) and text not in self.names and len(self.names) < 64)
        self.error.setText(
            "预设名称已存在"
            if text in self.names
            else "最多保存 64 个预设"
            if len(self.names) >= 64
            else ""
        )


def add_preset(parent, entries, state):
    dialog = PresetDialog({row["name"] for row in entries}, parent)
    try:
        if dialog.exec() and dialog.confirm.isEnabled():
            entries.append({"name": dialog.name.text().strip(), "state": copy.deepcopy(state)})
            return True
        return False
    finally:
        dialog.deleteLater()


class PresetSettings(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.entries = read_presets(panel.context)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("预设管理"), 1)
        add = QPushButton("新增")
        add.clicked.connect(self.add)
        row.addWidget(add)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        layout.addWidget(self.list)
        self.refresh()

    def refresh(self):
        self.list.clear()
        self.list.addItems([entry["name"] for entry in self.entries])

    def add(self):
        if add_preset(self, self.entries, self.panel.session.state):
            self.refresh()

    def reset(self):
        self.entries = []
        self.refresh()

    def save(self):
        self.panel.context.set_setting("presets", self.entries)
        self.panel.reload_presets()
        return True
