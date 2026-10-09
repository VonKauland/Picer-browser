"""Declarative per-component settings, validated before a single atomic commit."""

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from picer.host_style import mark_host


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    kind: str
    default: Any
    minimum: int = 0
    maximum: int = 100
    choices: tuple[tuple[str, str], ...] = ()

    def validate(self, value):
        if self.kind == "bool":
            return value if type(value) is bool else self.default
        if self.kind == "int":
            return (
                max(self.minimum, min(self.maximum, value)) if type(value) is int else self.default
            )
        if self.kind == "choice":
            return value if value in tuple(key for key, _ in self.choices) else self.default
        return value if isinstance(value, str) else self.default


class SettingsDialog(QDialog):
    def __init__(self, manager, plugin_id, parent=None):
        super().__init__(parent)
        self.manager, self.plugin_id = manager, plugin_id
        self.fields, self.callback = manager.settings_forms[plugin_id]
        self.setWindowTitle(manager.records[plugin_id].manifest.name + " · 插件设置")
        self.resize(480, 380)
        self.editors = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        for field in self.fields:
            value = field.validate(manager.get_setting(plugin_id, field.key, field.default))
            if field.kind == "bool":
                editor = QCheckBox()
                editor.setChecked(value)
            elif field.kind == "int":
                editor = QSpinBox()
                editor.setRange(field.minimum, field.maximum)
                editor.setValue(value)
            elif field.kind == "choice":
                editor = QComboBox()
                for key, label in field.choices:
                    editor.addItem(label, key)
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor = QLineEdit(value)
            self.editors[field.key] = editor
            if field.kind == "path":
                container = QWidget()
                row = QHBoxLayout(container)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(editor)
                browse = QPushButton("选择…")
                browse.clicked.connect(lambda _, edit=editor: self.choose_directory(edit))
                row.addWidget(browse)
                form.addRow(field.label, container)
            else:
                form.addRow(field.label, editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        mark_host(self)
        manager.changed.connect(self.check_active)

    def check_active(self):
        if self.plugin_id not in self.manager.settings_forms:
            self.reject()

    def choose_directory(self, editor):
        path = QFileDialog.getExistingDirectory(self, "选择首页路径", editor.text())
        if path:
            editor.setText(path)

    def save(self):
        from picer.plugins.api import PluginError

        values = {}
        for field in self.fields:
            editor = self.editors[field.key]
            value = (
                editor.isChecked()
                if field.kind == "bool"
                else editor.value()
                if field.kind == "int"
                else editor.currentData()
                if field.kind == "choice"
                else editor.text()
            )
            if field.kind == "path" and value:
                from pathlib import Path

                if not Path(value).expanduser().is_dir():
                    QMessageBox.warning(self, "设置未保存", "首页路径必须是存在的文件夹。")
                    return
            values[field.key] = field.validate(value)
        try:
            self.manager.set_settings(self.plugin_id, values)
        except PluginError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return
        self.manager._invoke(self.plugin_id, self.callback)
        self.accept()
